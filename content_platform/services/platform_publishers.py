from datetime import datetime, timezone
import json
import mimetypes
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .media import UPLOAD_DIR
from .rich_text import compose_publication_text, detect_social_entities, utf8_byte_range
from .social_accounts import decrypt_credentials_for_publisher


class PublicationError(Exception):
    pass


def publish_to_platform(post, media_items):
    if post["platform"] == "Bluesky":
        return publish_to_bluesky(post, media_items)
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

    image_embed = _build_bluesky_image_embed(pds_url, access_jwt, media_items)
    if image_embed:
        record["embed"] = image_embed

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
        path = (UPLOAD_DIR / media_item["filename"]).resolve()
        if not path.exists() or UPLOAD_DIR.resolve() not in path.parents:
            raise PublicationError(f"Media file is missing: {media_item['original_filename']}")
        blob = _upload_bluesky_blob(pds_url, access_jwt, path)
        images.append({"alt": media_item["original_filename"], "image": blob})

    if not images:
        return None
    return {"$type": "app.bsky.embed.images", "images": images}


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


def _post_json(url, payload, access_jwt=None, endpoint_name="request"):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if access_jwt:
        headers["Authorization"] = f"Bearer {access_jwt}"
    return _request_json(Request(url, data=data, headers=headers, method="POST"), endpoint_name)


def _post_bytes(url, payload, content_type, access_jwt, endpoint_name="request"):
    headers = {"Content-Type": content_type, "Authorization": f"Bearer {access_jwt}"}
    return _request_json(Request(url, data=payload, headers=headers, method="POST"), endpoint_name)


def _request_json(request, endpoint_name):
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublicationError(f"Bluesky API {endpoint_name} error {exc.code}: {_clean_error_detail(detail)}") from exc
    except (URLError, TimeoutError) as exc:
        raise PublicationError(f"Bluesky API {endpoint_name} request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PublicationError(f"Bluesky API {endpoint_name} returned an invalid JSON response.") from exc


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
