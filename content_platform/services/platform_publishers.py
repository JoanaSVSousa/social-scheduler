from datetime import datetime, timezone
import json
import mimetypes
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .media import UPLOAD_DIR
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
    pds_url = (credentials.get("pds_url") or "https://bsky.social").rstrip("/")
    if not identifier or not app_password:
        raise PublicationError("Bluesky needs a handle/email and an app password.")

    session = _post_json(
        f"{pds_url}/xrpc/com.atproto.server.createSession",
        {"identifier": identifier, "password": app_password},
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
    )
    return response.get("uri") or "Bluesky post created"


def _compose_bluesky_text(post):
    pieces = [post["content"].strip(), post["hashtags"].strip()]
    text = "\n\n".join(piece for piece in pieces if piece)
    if not text:
        text = post["title"].strip()
    if len(text) > 300:
        raise PublicationError("Bluesky posts must be 300 characters or less. Shorten this version before publishing.")
    return text


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
    )
    blob = response.get("blob")
    if not blob:
        raise PublicationError("Bluesky did not return a blob reference for uploaded media.")
    return blob


def _post_json(url, payload, access_jwt=None):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if access_jwt:
        headers["Authorization"] = f"Bearer {access_jwt}"
    return _request_json(Request(url, data=data, headers=headers, method="POST"))


def _post_bytes(url, payload, content_type, access_jwt):
    headers = {"Content-Type": content_type, "Authorization": f"Bearer {access_jwt}"}
    return _request_json(Request(url, data=payload, headers=headers, method="POST"))


def _request_json(request):
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublicationError(f"Bluesky API error {exc.code}: {detail}") from exc
    except (URLError, TimeoutError) as exc:
        raise PublicationError(f"Bluesky API request failed: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise PublicationError("Bluesky API returned an invalid JSON response.") from exc
