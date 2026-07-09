import base64
from datetime import datetime, timezone
import hashlib
from html import unescape
import hmac
import json
import mimetypes
from pathlib import Path
import re
import secrets
from tempfile import gettempdir
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from ..database import get_connection
from .media import UPLOAD_DIR
from .media_optimizer import DEFAULT_IMAGE_LIMIT_BYTES, optimize_image_bytes
from .rich_text import compose_publication_text, detect_social_entities, utf8_byte_range
from .social_accounts import decrypt_credentials_for_publisher


class PublicationError(Exception):
    pass


IMPLEMENTED_PUBLISHERS = {"Bluesky", "X"}


def is_platform_publishable(platform):
    return platform in IMPLEMENTED_PUBLISHERS


def publish_to_platform(post, media_items):
    if post["platform"] == "Bluesky":
        return publish_to_bluesky(post, media_items)
    if post["platform"] == "X":
        return publish_to_x(post, media_items)
    raise PublicationError(f"Real API publishing is not implemented yet for {post['platform']}.")


def publish_to_bluesky(post, media_items):
    account = decrypt_credentials_for_publisher("Bluesky")
    if not account:
        raise PublicationError("Bluesky credentials are not configured.")

    credentials = account["credentials"]
    identifier = credentials.get("identifier") or account.get("account_handle")
    app_password = credentials.get("app_password")
    pds_url = _normalize_bluesky_pds_url(credentials.get("pds_url"))
    if not identifier or not app_password:
        raise PublicationError("Bluesky needs a handle/email and an app password.")

    session = _post_json(
        f"{pds_url}/xrpc/com.atproto.server.createSession",
        {"identifier": identifier, "password": app_password},
        endpoint_name="createSession",
    )
    access_jwt = session.get("accessJwt")
    repo = session.get("did") or identifier
    if not access_jwt or not repo:
        raise PublicationError("Bluesky session did not return the expected tokens.")

    text = _compose_bluesky_text(post)
    record = {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    facets = _build_bluesky_facets(text)
    if facets:
        record["facets"] = facets

    record_embed = _build_bluesky_image_embed(pds_url, access_jwt, media_items)
    if not record_embed:
        record_embed = _build_bluesky_external_embed(pds_url, access_jwt, post)
    if record_embed:
        record["embed"] = record_embed

    response = _post_json(
        f"{pds_url}/xrpc/com.atproto.repo.createRecord",
        {
            "repo": repo,
            "collection": "app.bsky.feed.post",
            "record": record,
        },
        access_jwt=access_jwt,
        endpoint_name="createRecord",
    )
    return response.get("uri") or "Bluesky post created"


def publish_to_x(post, media_items):
    account = decrypt_credentials_for_publisher("X")
    if not account:
        raise PublicationError("X credentials are not configured.")

    credentials = account["credentials"]
    oauth_header = _x_oauth1_header("POST", "https://api.x.com/2/tweets", credentials)
    access_token = credentials.get("oauth2_user_token") or credentials.get("bearer_token")
    if not oauth_header and not access_token:
        raise PublicationError(
            "X needs either OAuth 1.0a user credentials or an OAuth2 User Access Token with tweet.write permission."
        )

    text = compose_publication_text("X", post["content"], post["hashtags"])
    if not text:
        raise PublicationError("Post content is empty. The title is internal and is not published.")
    if len(text) > 280:
        raise PublicationError("X posts must be 280 characters or less. Shorten this version before publishing.")

    response = _post_json(
        "https://api.x.com/2/tweets",
        {"text": text},
        access_jwt=None if oauth_header else access_token,
        auth_header=oauth_header,
        endpoint_name="X create post",
        error_label="X API",
    )
    post_id = (response.get("data") or {}).get("id")
    suffix = " Media upload for X is not implemented yet." if media_items else ""
    return f"https://x.com/i/web/status/{post_id}{suffix}" if post_id else f"X post created.{suffix}"


def _x_oauth1_header(method, url, credentials):
    required = ["api_key", "api_secret", "access_token", "access_token_secret"]
    if any(not credentials.get(key) for key in required):
        return ""

    oauth_params = {
        "oauth_consumer_key": credentials["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": credentials["access_token"],
        "oauth_version": "1.0",
    }
    signature_params = "&".join(
        f"{_oauth_quote(key)}={_oauth_quote(value)}"
        for key, value in sorted(oauth_params.items())
    )
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    signature_base = "&".join(
        [_oauth_quote(method.upper()), _oauth_quote(base_url), _oauth_quote(signature_params)]
    )
    signing_key = f"{_oauth_quote(credentials['api_secret'])}&{_oauth_quote(credentials['access_token_secret'])}"
    digest = hmac.new(signing_key.encode("utf-8"), signature_base.encode("utf-8"), hashlib.sha1).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode("utf-8")
    return "OAuth " + ", ".join(
        f'{_oauth_quote(key)}="{_oauth_quote(value)}"'
        for key, value in sorted(oauth_params.items())
    )


def _oauth_quote(value):
    return quote(str(value), safe="~")


def _compose_bluesky_text(post):
    text = compose_publication_text("Bluesky", post["content"], post["hashtags"])
    if not text:
        raise PublicationError("Post content is empty. The title is internal and is not published.")
    if len(text) > 300:
        raise PublicationError("Bluesky hashtags are too long to fit in a 300-character post.")
    return text


def _build_bluesky_facets(text):
    """Tell Bluesky which text ranges are clickable links and valid hashtags."""
    facets = []
    for entity in detect_social_entities(text):
        feature = _bluesky_facet_feature(entity)
        if not feature:
            continue
        facets.append(
            {
                "index": utf8_byte_range(text, entity["start"], entity["end"]),
                "features": [feature],
            }
        )
    return facets


def _bluesky_facet_feature(entity):
    if entity["type"] == "link":
        return {"$type": "app.bsky.richtext.facet#link", "uri": entity["value"]}
    if entity["type"] == "hashtag":
        return {"$type": "app.bsky.richtext.facet#tag", "tag": entity["value"]}
    return None


def _build_bluesky_image_embed(pds_url, access_jwt, media_items):
    images = []
    for media_item in media_items[:4]:
        if media_item["media_type"] != "image":
            raise PublicationError("Bluesky publisher currently supports image media only. Remove video media for this test.")
        path = _publish_path_for_media(media_item)
        if not path.exists() or UPLOAD_DIR.resolve() not in path.parents:
            if not _is_optimized_publish_path(path):
                raise PublicationError(f"Media file is missing: {media_item['original_filename']}")
        blob = _upload_bluesky_blob(pds_url, access_jwt, path)
        images.append({"alt": media_item["original_filename"], "image": blob})

    if not images:
        return None
    return {"$type": "app.bsky.embed.images", "images": images}


def _build_bluesky_external_embed(pds_url, access_jwt, post):
    if not _should_use_external_embed(post):
        return None

    source = _source_link_for_post(post)
    if not source:
        return None

    card = {
        "uri": source["url"],
        "title": source["title"] or post["title"],
        "description": (source["description"] or post["content"] or "")[:300],
    }
    thumb = _upload_bluesky_remote_thumb(pds_url, access_jwt, source.get("image_url"))
    if thumb:
        card["thumb"] = thumb
    return {"$type": "app.bsky.embed.external", "external": card}


def _should_use_external_embed(post):
    if post["platform"] != "Bluesky":
        return False
    normalized_format = (post["content_format"] or "").lower()
    return any(label in normalized_format for label in ["text", "thread", "link", "article"])


def _source_link_for_post(post):
    rss_item_id = _post_value(post, "rss_item_id", "")
    if rss_item_id:
        with get_connection() as conn:
            item = conn.execute(
                "SELECT title, url, image_url FROM rss_items WHERE id = ?",
                (rss_item_id,),
            ).fetchone()
        if item:
            image_url = item["image_url"] or _find_page_image_url(item["url"])
            if image_url and image_url != item["image_url"]:
                _remember_rss_item_image(rss_item_id, image_url)
            return {
                "title": item["title"],
                "url": item["url"],
                "image_url": image_url,
                "description": post["content"],
            }

    links = [entity for entity in detect_social_entities(post["content"]) if entity["type"] == "link"]
    if not links:
        return None
    return {
        "title": post["title"],
        "url": links[0]["value"],
        "image_url": "",
        "description": post["content"],
    }


def _post_value(post, key, fallback=None):
    if hasattr(post, "keys") and key not in post.keys():
        return fallback
    try:
        return post[key]
    except (KeyError, TypeError):
        return fallback


def _find_page_image_url(page_url):
    try:
        request = Request(
            page_url,
            headers={"User-Agent": "ContentAutomationPlatform/1.0 (+https://squared-potato.pt)"},
        )
        with urlopen(request, timeout=12) as response:
            html = response.read(500_000).decode("utf-8", errors="replace")
    except (HTTPError, URLError, TimeoutError, ValueError):
        return ""

    image_url = (
        _html_meta_content(html, "property", "og:image")
        or _html_meta_content(html, "name", "twitter:image")
        or _first_image_src(html)
    )
    return urljoin(page_url, image_url) if image_url else ""


def _html_meta_content(html, attribute_name, attribute_value):
    pattern = (
        rf"<meta[^>]+{attribute_name}=[\"']{re.escape(attribute_value)}[\"'][^>]+content=[\"']([^\"']+)[\"']"
        rf"|<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+{attribute_name}=[\"']{re.escape(attribute_value)}[\"']"
    )
    match = re.search(pattern, html, re.IGNORECASE)
    if not match:
        return ""
    return unescape(next(group for group in match.groups() if group)).strip()


def _first_image_src(html):
    match = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", html, re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def _remember_rss_item_image(rss_item_id, image_url):
    with get_connection() as conn:
        conn.execute(
            "UPDATE rss_items SET image_url = ? WHERE id = ? AND (image_url IS NULL OR image_url = '')",
            (image_url, rss_item_id),
        )


def _upload_bluesky_remote_thumb(pds_url, access_jwt, image_url):
    if not image_url:
        return None
    try:
        with urlopen(image_url, timeout=12) as response:
            data = response.read(8_000_001)
            content_type = response.headers.get_content_type() or "image/jpeg"
    except (HTTPError, URLError, TimeoutError, ValueError):
        return None
    if not content_type.startswith("image/"):
        return None
    if len(data) > DEFAULT_IMAGE_LIMIT_BYTES:
        data = optimize_image_bytes(data, image_limit_bytes=DEFAULT_IMAGE_LIMIT_BYTES)
        content_type = "image/jpeg"
    if not data or len(data) > DEFAULT_IMAGE_LIMIT_BYTES:
        return None
    try:
        response = _post_bytes(
            f"{pds_url}/xrpc/com.atproto.repo.uploadBlob",
            data,
            content_type,
            access_jwt,
            endpoint_name="uploadBlob",
        )
    except PublicationError:
        return None
    return response.get("blob")


def _upload_bluesky_blob(pds_url, access_jwt, path):
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    with path.open("rb") as media_file:
        data = media_file.read()
    response = _post_bytes(
        f"{pds_url}/xrpc/com.atproto.repo.uploadBlob",
        data,
        content_type,
        access_jwt,
        endpoint_name="uploadBlob",
    )
    blob = response.get("blob")
    if not blob:
        raise PublicationError("Bluesky did not return a blob reference for uploaded media.")
    return blob


def _publish_path_for_media(media_item):
    value = media_item.get("publish_path") if hasattr(media_item, "get") else None
    if value:
        return Path(value).resolve()
    return (UPLOAD_DIR / media_item["filename"]).resolve()


def _is_optimized_publish_path(path):
    try:
        return Path(path).resolve().is_relative_to(Path(gettempdir()).resolve())
    except AttributeError:
        resolved = str(Path(path).resolve())
        return resolved.startswith(str(Path(gettempdir()).resolve()))


def _normalize_bluesky_pds_url(value):
    value = (value or "").strip()
    if not value:
        return "https://bsky.social"
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    hostname = (parsed.hostname or "").lower()
    if hostname in {"bsky.app", "www.bsky.app"}:
        return "https://bsky.social"
    if not parsed.scheme.startswith("http") or not hostname:
        raise PublicationError("Bluesky PDS URL must be a valid URL, for example https://bsky.social.")
    if parsed.path not in {"", "/"}:
        raise PublicationError("Bluesky PDS URL must be the server root, for example https://bsky.social, not a profile/post URL.")
    return f"{parsed.scheme}://{parsed.netloc}".rstrip("/")


def _post_json(url, payload, access_jwt=None, auth_header=None, endpoint_name="request", error_label="Bluesky API"):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if auth_header:
        headers["Authorization"] = auth_header
    elif access_jwt:
        headers["Authorization"] = f"Bearer {access_jwt}"
    return _request_json(Request(url, data=data, headers=headers, method="POST"), endpoint_name, error_label)


def _post_bytes(url, payload, content_type, access_jwt, endpoint_name="request", error_label="Bluesky API"):
    headers = {"Content-Type": content_type, "Authorization": f"Bearer {access_jwt}"}
    return _request_json(Request(url, data=payload, headers=headers, method="POST"), endpoint_name, error_label)


def _request_json(request, endpoint_name, error_label):
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublicationError(f"{error_label} {endpoint_name} error {exc.code}: {_clean_error_detail(detail)}") from exc
    except (URLError, TimeoutError) as exc:
        raise PublicationError(f"{error_label} {endpoint_name} request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PublicationError(f"{error_label} {endpoint_name} returned an invalid JSON response.") from exc


def _clean_error_detail(detail):
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return payload.get("message") or payload.get("error") or json.dumps(payload)

    text = re.sub(r"<[^>]+>", " ", detail)
    text = re.sub(r"\s+", " ", text).strip()
    if "404: Not Found" in text or "Error 404" in text:
        return "Endpoint not found. Check that Bluesky PDS URL is https://bsky.social, not bsky.app or a profile URL."
    return text[:500] or "No response body."
