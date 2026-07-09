from io import BytesIO
from pathlib import Path
from tempfile import gettempdir
from uuid import uuid4

from ..database import get_connection
from .media import UPLOAD_DIR
from .public_media import PublicMediaError, upload_public_media


OPTIMIZED_MEDIA_DIR = Path(gettempdir()) / "content_automation_platform_media"
DEFAULT_IMAGE_LIMIT_BYTES = 1_900_000
DEFAULT_MAX_DIMENSION = 1800


def prepare_media_for_publish(media_items, image_limit_bytes=DEFAULT_IMAGE_LIMIT_BYTES):
    prepared = []
    for media_item in media_items:
        item = dict(media_item)
        path = (UPLOAD_DIR / item["filename"]).resolve()
        item["publish_path"] = path
        item["publish_content_type"] = _content_type_for_path(path)
        if not item.get("public_url"):
            item["public_url"] = _ensure_public_url(item, path)

        if item["media_type"] == "image":
            optimized = optimize_image_file(path, image_limit_bytes=image_limit_bytes)
            if optimized:
                item["publish_path"] = optimized["path"]
                item["publish_content_type"] = optimized["content_type"]

        prepared.append(item)
    return prepared


def _ensure_public_url(media_item, path):
    if not path.exists():
        return ""
    try:
        public_url = upload_public_media(path, f"posts/{media_item['post_id']}/{media_item['filename']}")
    except (KeyError, PublicMediaError):
        return ""
    if public_url:
        with get_connection() as conn:
            conn.execute(
                "UPDATE media_assets SET public_url = ? WHERE id = ?",
                (public_url, media_item["id"]),
            )
    return public_url


def optimize_image_file(path, image_limit_bytes=DEFAULT_IMAGE_LIMIT_BYTES):
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) <= image_limit_bytes:
        return {"path": path, "content_type": _content_type_for_path(path)}

    optimized_data = optimize_image_bytes(data, image_limit_bytes=image_limit_bytes)
    if not optimized_data:
        return None

    OPTIMIZED_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    optimized_path = OPTIMIZED_MEDIA_DIR / f"{uuid4().hex}.jpg"
    optimized_path.write_bytes(optimized_data)
    return {"path": optimized_path, "content_type": "image/jpeg"}


def optimize_image_bytes(data, image_limit_bytes=DEFAULT_IMAGE_LIMIT_BYTES):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return data if len(data) <= image_limit_bytes else None

    try:
        image = Image.open(BytesIO(data))
        image = ImageOps.exif_transpose(image)
    except Exception:
        return data if len(data) <= image_limit_bytes else None

    if image.mode not in {"RGB", "L"}:
        background = Image.new("RGB", image.size, (255, 255, 255))
        if image.mode in {"RGBA", "LA"}:
            alpha = image.getchannel("A")
            background.paste(image.convert("RGB"), mask=alpha)
        else:
            background.paste(image.convert("RGB"))
        image = background
    else:
        image = image.convert("RGB")

    for max_dimension in (DEFAULT_MAX_DIMENSION, 1600, 1400, 1200, 1000, 800):
        resized = _resize_to_max_dimension(image, max_dimension)
        for quality in (88, 82, 76, 70, 64, 58, 52):
            output = BytesIO()
            resized.save(output, format="JPEG", quality=quality, optimize=True, progressive=True)
            payload = output.getvalue()
            if len(payload) <= image_limit_bytes:
                return payload

    output = BytesIO()
    _resize_to_max_dimension(image, 720).save(output, format="JPEG", quality=46, optimize=True)
    payload = output.getvalue()
    return payload if len(payload) <= image_limit_bytes else None


def _resize_to_max_dimension(image, max_dimension):
    width, height = image.size
    largest_side = max(width, height)
    if largest_side <= max_dimension:
        return image.copy()

    scale = max_dimension / largest_side
    size = (max(1, int(width * scale)), max(1, int(height * scale)))
    return image.resize(size)


def _content_type_for_path(path):
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    if suffix == ".gif":
        return "image/gif"
    return "application/octet-stream"
