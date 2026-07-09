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
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from ..database import get_connection
from .media import UPLOAD_DIR
from .media_optimizer import DEFAULT_IMAGE_LIMIT_BYTES, optimize_image_bytes
from .rich_text import compose_publication_text, detect_social_entities, utf8_byte_range
from .social_accounts import decrypt_credentials_for_publisher


class PublicationError(Exception):
    pass


IMPLEMENTED_PUBLISHERS = {
    "Bluesky",
    "Facebook",
    "Instagram",
    "LinkedIn",
    "Threads",
    "TikTok",
    "X",
    "YouTube Shorts",
}


def is_platform_publishable(platform):
    return platform in IMPLEMENTED_PUBLISHERS


def publish_to_platform(post, media_items):
    if post["platform"] == "Bluesky":
        return publish_to_bluesky(post, media_items)
    if post["platform"] == "Facebook":
        return publish_to_facebook(post, media_items)
    if post["platform"] == "Instagram":
        return publish_to_instagram(post, media_items)
    if post["platform"] == "LinkedIn":
        return publish_to_linkedin(post, media_items)
    if post["platform"] == "Threads":
        return publish_to_threads(post, media_items)
    if post["platform"] == "TikTok":
        return publish_to_tiktok(post, media_items)
    if post["platform"] == "X":
        return publish_to_x(post, media_items)
    if post["platform"] == "YouTube Shorts":
        return publish_to_youtube_shorts(post, media_items)
    raise PublicationError(f"Real API publishing is not implemented yet for {post['platform']}.")


def publish_to_threads(post, media_items):
    account = decrypt_credentials_for_publisher("Threads")
    if not account:
        raise PublicationError("Threads credentials are not configured.")

    credentials = account["credentials"]
    threads_user_id = credentials.get("threads_user_id") or account.get("account_handle")
    access_token = credentials.get("access_token")
    if not threads_user_id or not access_token:
        raise PublicationError("Threads needs a Threads User ID and a user access token with publishing permissions.")
    text = compose_publication_text("Threads", post["content"], post["hashtags"])
    if not text:
        raise PublicationError("Post content is empty. The title is internal and is not published.")
    if len(text) > 500:
        raise PublicationError("Threads posts must be 500 characters or less. Shorten this version before publishing.")

    media_payload = _threads_media_payload(media_items)
    container = _post_form(
        f"https://graph.threads.net/v1.0/{threads_user_id}/threads",
        {"text": text, "access_token": access_token, **media_payload},
        endpoint_name="Threads create container",
        error_label="Threads API",
    )
    creation_id = container.get("id")
    if not creation_id:
        raise PublicationError("Threads did not return a creation container id.")

    response = _post_form(
        f"https://graph.threads.net/v1.0/{threads_user_id}/threads_publish",
        {"creation_id": creation_id, "access_token": access_token},
        endpoint_name="Threads publish container",
        error_label="Threads API",
    )
    post_id = response.get("id")
    return f"Threads post created: {post_id}" if post_id else "Threads post created."


def publish_to_facebook(post, media_items):
    account = decrypt_credentials_for_publisher("Facebook")
    if not account:
        raise PublicationError("Facebook credentials are not configured.")

    credentials = account["credentials"]
    page_id = credentials.get("page_id") or account.get("account_handle")
    access_token = credentials.get("access_token")
    if not page_id or not access_token:
        raise PublicationError("Facebook needs a Page ID and a Page access token with publishing permissions.")
    text = compose_publication_text("Facebook", post["content"], post["hashtags"])
    if not text:
        raise PublicationError("Post content is empty. The title is internal and is not published.")

    public_media = _first_public_media(media_items)
    if media_items and not public_media:
        raise PublicationError("Facebook media publishing needs a public image/video URL. Configure Supabase Storage public media first.")
    if public_media and public_media["media_type"] == "image":
        response = _post_form(
            f"https://graph.facebook.com/v20.0/{page_id}/photos",
            {"url": public_media["public_url"], "caption": text, "access_token": access_token},
            endpoint_name="Facebook Page photo publish",
            error_label="Facebook API",
        )
    elif public_media and public_media["media_type"] == "video":
        response = _post_form(
            f"https://graph.facebook.com/v20.0/{page_id}/videos",
            {"file_url": public_media["public_url"], "description": text, "access_token": access_token},
            endpoint_name="Facebook Page video publish",
            error_label="Facebook API",
        )
    else:
        payload = {"message": text, "access_token": access_token}
        source = _source_link_for_post(post)
        if source and source.get("url"):
            payload["link"] = source["url"]
        response = _post_form(
            f"https://graph.facebook.com/v20.0/{page_id}/feed",
            payload,
            endpoint_name="Facebook Page feed publish",
            error_label="Facebook API",
        )
    post_id = response.get("id")
    return f"https://facebook.com/{post_id}" if post_id else "Facebook Page post created."


def publish_to_instagram(post, media_items):
    account = decrypt_credentials_for_publisher("Instagram")
    if not account:
        raise PublicationError("Instagram credentials are not configured.")

    credentials = account["credentials"]
    instagram_id = credentials.get("instagram_business_id") or account.get("account_handle")
    access_token = credentials.get("access_token")
    if not instagram_id or not access_token:
        raise PublicationError("Instagram needs an Instagram Business ID and a Meta access token with content publishing permissions.")

    normalized_format = (post["content_format"] or "").lower()
    public_media = _first_public_media(media_items)
    if media_items and not public_media:
        raise PublicationError("Instagram publishing needs a public image/video URL for uploaded media. Configure Supabase Storage public media first.")
    source = _source_link_for_post(post)
    caption = compose_publication_text("Instagram", post["content"], post["hashtags"])
    if not caption:
        raise PublicationError("Post content is empty. The title is internal and is not published.")

    payload = {"caption": caption, "access_token": access_token}
    if any(label in normalized_format for label in ["reel", "video"]):
        if not public_media or public_media["media_type"] != "video":
            raise PublicationError("Instagram Reels/video publishing needs a public video URL from an uploaded video.")
        payload.update({"media_type": "REELS", "video_url": public_media["public_url"]})
    elif "story" in normalized_format:
        if not public_media:
            raise PublicationError("Instagram Story publishing needs a public image or video URL from uploaded media.")
        if public_media["media_type"] == "video":
            payload.update({"media_type": "STORIES", "video_url": public_media["public_url"]})
        else:
            payload.update({"media_type": "STORIES", "image_url": public_media["public_url"]})
    elif public_media:
        if public_media["media_type"] != "image":
            raise PublicationError("Instagram feed image publishing needs a public image URL. Choose Reel/Video for video media.")
        payload["image_url"] = public_media["public_url"]
    else:
        image_url = (source or {}).get("image_url")
        if not image_url:
            raise PublicationError("Instagram feed publishing needs a public image URL. Upload media or use an RSS/article image.")
        payload["image_url"] = image_url

    container = _post_form(
        f"https://graph.facebook.com/v20.0/{instagram_id}/media",
        payload,
        endpoint_name="Instagram create media container",
        error_label="Instagram API",
    )
    creation_id = container.get("id")
    if not creation_id:
        raise PublicationError("Instagram did not return a media container id.")

    response = _post_form(
        f"https://graph.facebook.com/v20.0/{instagram_id}/media_publish",
        {"creation_id": creation_id, "access_token": access_token},
        endpoint_name="Instagram publish media",
        error_label="Instagram API",
    )
    media_id = response.get("id")
    return f"Instagram media published: {media_id}" if media_id else "Instagram media published."


def publish_to_linkedin(post, media_items):
    account = decrypt_credentials_for_publisher("LinkedIn")
    if not account:
        raise PublicationError("LinkedIn credentials are not configured.")

    credentials = account["credentials"]
    access_token = credentials.get("access_token")
    author = _linkedin_author_urn(credentials.get("organization_id") or account.get("account_handle"))
    if not access_token or not author:
        raise PublicationError("LinkedIn needs an access token and an organization/person URN.")
    if media_items:
        raise PublicationError("LinkedIn media publishing needs asset registration/upload support. This MVP currently supports text/link posts.")

    text = compose_publication_text("LinkedIn", post["content"], post["hashtags"])
    if not text:
        raise PublicationError("Post content is empty. The title is internal and is not published.")

    source = _source_link_for_post(post)
    share_content = {
        "shareCommentary": {"text": text},
        "shareMediaCategory": "NONE",
    }
    if source and source.get("url"):
        share_content["shareMediaCategory"] = "ARTICLE"
        share_content["media"] = [
            {
                "status": "READY",
                "originalUrl": source["url"],
                "title": {"text": (source.get("title") or post["title"])[:200]},
            }
        ]

    payload = {
        "author": author,
        "lifecycleState": "PUBLISHED",
        "specificContent": {"com.linkedin.ugc.ShareContent": share_content},
        "visibility": {"com.linkedin.ugc.MemberNetworkVisibility": "PUBLIC"},
    }
    response = _post_json(
        "https://api.linkedin.com/v2/ugcPosts",
        payload,
        access_jwt=access_token,
        endpoint_name="LinkedIn create UGC post",
        error_label="LinkedIn API",
        extra_headers={"X-Restli-Protocol-Version": "2.0.0"},
    )
    return response.get("id") or "LinkedIn post created."


def publish_to_youtube_shorts(post, media_items):
    if not decrypt_credentials_for_publisher("YouTube Shorts"):
        raise PublicationError("YouTube Shorts credentials are not configured.")
    raise PublicationError("YouTube Shorts publishing needs a resumable video upload workflow. Credentials can be stored now; upload publishing is the next implementation step.")


def publish_to_tiktok(post, media_items):
    if not decrypt_credentials_for_publisher("TikTok"):
        raise PublicationError("TikTok credentials are not configured.")
    raise PublicationError("TikTok publishing needs the Content Posting API upload/init flow. Credentials can be stored now; upload publishing is the next implementation step.")


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
    auth_type = account.get("auth_type") or "oauth1"
    oauth_header = _x_oauth1_header("POST", "https://api.x.com/2/tweets", credentials) if auth_type == "oauth1" else ""
    access_token = credentials.get("oauth2_user_token") if auth_type == "oauth2" else ""
    if auth_type == "oauth2" and not access_token:
        raise PublicationError(
            "X OAuth2 needs a User Access Token with tweet.write. Client ID, Client Secret, and app-only Bearer Token cannot publish."
        )
    if auth_type == "oauth1" and not oauth_header:
        raise PublicationError(
            "X OAuth1 needs API Key, API Key Secret, Access Token, and Access Token Secret."
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


def _linkedin_author_urn(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value.startswith("urn:li:"):
        return value
    if value.isdigit():
        return f"urn:li:organization:{value}"
    return value


def _first_public_media(media_items, media_type=None):
    for item in media_items:
        public_url = item.get("public_url") if hasattr(item, "get") else ""
        item_type = item.get("media_type") if hasattr(item, "get") else ""
        if public_url and (media_type is None or item_type == media_type):
            return {"public_url": public_url, "media_type": item_type}
    return None


def _threads_media_payload(media_items):
    public_media = _first_public_media(media_items)
    if not media_items:
        return {"media_type": "TEXT"}
    if not public_media:
        raise PublicationError(
            "Threads media publishing needs a public image_url/video_url. Upload media after configuring Supabase Storage public media first."
        )
    if public_media["media_type"] == "image":
        return {"media_type": "IMAGE", "image_url": public_media["public_url"]}
    if public_media["media_type"] == "video":
        return {"media_type": "VIDEO", "video_url": public_media["public_url"]}
    raise PublicationError("Threads supports image or video media for this publisher.")


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


def _post_json(
    url,
    payload,
    access_jwt=None,
    auth_header=None,
    endpoint_name="request",
    error_label="Bluesky API",
    extra_headers=None,
):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if auth_header:
        headers["Authorization"] = auth_header
    elif access_jwt:
        headers["Authorization"] = f"Bearer {access_jwt}"
    return _request_json(Request(url, data=data, headers=headers, method="POST"), endpoint_name, error_label)


def _post_form(url, payload, endpoint_name="request", error_label="API"):
    data = urlencode(payload).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    return _request_json(Request(url, data=data, headers=headers, method="POST"), endpoint_name, error_label)


def _post_bytes(url, payload, content_type, access_jwt, endpoint_name="request", error_label="Bluesky API"):
    headers = {"Content-Type": content_type, "Authorization": f"Bearer {access_jwt}"}
    return _request_json(Request(url, data=payload, headers=headers, method="POST"), endpoint_name, error_label)


def _request_json(request, endpoint_name, error_label):
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body.strip() else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if error_label == "X API" and exc.code in {401, 403}:
            detail = f"{_clean_error_detail(detail)} {_x_auth_help()}"
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
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or json.dumps(error)
            code = error.get("code")
            error_type = error.get("type")
            details = " ".join(str(value) for value in [error_type, f"code {code}" if code else ""] if value)
            return f"{message} {details}".strip()
        return payload.get("message") or error or json.dumps(payload)

    text = re.sub(r"<[^>]+>", " ", detail)
    text = re.sub(r"\s+", " ", text).strip()
    if "404: Not Found" in text or "Error 404" in text:
        return "Endpoint not found. Check that Bluesky PDS URL is https://bsky.social, not bsky.app or a profile URL."
    return text[:500] or "No response body."


def _x_auth_help():
    return (
        "Check X credentials: OAuth1 uses API Key/API Key Secret, not OAuth2 Client ID/Client Secret; "
        "the app must have Read and Write permissions; regenerate the user Access Token and Access Token Secret "
        "after changing permissions. OAuth2 must be User Context with tweet.write, not application-only bearer. "
        "If X says client-not-enrolled or Appropriate Level of API Access, the app credentials may be valid but the "
        "Project/API product is not enrolled in an access level that allows POST /2/tweets."
    )
