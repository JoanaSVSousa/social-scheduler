import mimetypes
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class PublicMediaError(Exception):
    pass


def upload_public_media(local_path, storage_name):
    """Upload media to Supabase Storage when configured, returning a public URL."""
    supabase_url = _clean_url(os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL"))
    service_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_STORAGE_KEY")
    bucket = os.environ.get("SUPABASE_MEDIA_BUCKET", "social-media")
    if not supabase_url or not service_key:
        return ""

    path = Path(local_path)
    if not path.exists():
        raise PublicMediaError("Local media file does not exist.")

    object_name = _object_name(storage_name)
    upload_url = f"{supabase_url}/storage/v1/object/{quote(bucket)}/{object_name}"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {
        "Authorization": f"Bearer {service_key}",
        "apikey": service_key,
        "Content-Type": content_type,
        "x-upsert": "true",
    }
    try:
        with path.open("rb") as media_file:
            request = Request(upload_url, data=media_file.read(), headers=headers, method="POST")
        with urlopen(request, timeout=30) as response:
            response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublicMediaError(f"Supabase Storage upload failed {exc.code}: {detail[:300]}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise PublicMediaError(f"Supabase Storage upload failed: {exc}") from exc

    return f"{supabase_url}/storage/v1/object/public/{quote(bucket)}/{object_name}"


def _clean_url(value):
    return (value or "").strip().rstrip("/")


def _object_name(storage_name):
    safe_name = str(storage_name).strip().lstrip("/")
    return quote(safe_name, safe="/")
