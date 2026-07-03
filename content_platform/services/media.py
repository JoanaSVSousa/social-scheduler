from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename

from ..database import PROJECT_ROOT, get_connection


UPLOAD_DIR = PROJECT_ROOT / "static" / "uploads"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "mp4", "mov", "m4v", "webm"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
VIDEO_EXTENSIONS = {"mp4", "mov", "m4v", "webm"}
MAX_FILE_SIZE = 20 * 1024 * 1024


def save_media_files(post_id, files):
    saved = []
    skipped = []
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    for file in files:
        if not file or not file.filename:
            continue

        extension = _extension(file.filename)
        if extension not in ALLOWED_EXTENSIONS or not _is_safe_upload(file, extension):
            skipped.append(file.filename)
            continue

        original_filename = secure_filename(file.filename)
        if not original_filename:
            skipped.append(file.filename)
            continue

        filename = f"{uuid4().hex}.{extension}"
        file.save(UPLOAD_DIR / filename)
        media_type = "video" if extension in VIDEO_EXTENSIONS else "image"

        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO media_assets (post_id, filename, original_filename, media_type)
                VALUES (?, ?, ?, ?)
                """,
                (post_id, filename, original_filename, media_type),
            )

        saved.append(filename)

    return saved, skipped


def get_media_for_post(post_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM media_assets WHERE post_id = ? ORDER BY created_at ASC, id ASC",
            (post_id,),
        ).fetchall()


def get_media_for_posts(post_ids):
    if not post_ids:
        return {}

    placeholders = ",".join("?" for _ in post_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM media_assets
            WHERE post_id IN ({placeholders})
            ORDER BY created_at ASC, id ASC
            """,
            post_ids,
        ).fetchall()

    media_by_post = {post_id: [] for post_id in post_ids}
    for row in rows:
        media_by_post[row["post_id"]].append(row)
    return media_by_post


def delete_media(media_id):
    with get_connection() as conn:
        media = conn.execute("SELECT * FROM media_assets WHERE id = ?", (media_id,)).fetchone()
        if media is None:
            return
        conn.execute("DELETE FROM media_assets WHERE id = ?", (media_id,))

    path = (UPLOAD_DIR / media["filename"]).resolve()
    if UPLOAD_DIR.resolve() in path.parents and path.exists():
        path.unlink()


def _extension(filename):
    if "." not in filename:
        return ""
    return filename.rsplit(".", 1)[1].lower()


def _is_safe_upload(file, extension):
    stream = file.stream
    position = stream.tell()
    header = stream.read(32)
    stream.seek(0, 2)
    size = stream.tell()
    stream.seek(position)

    if size > MAX_FILE_SIZE:
        return False

    if extension == "png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {"jpg", "jpeg"}:
        return header.startswith(b"\xff\xd8\xff")
    if extension == "gif":
        return header.startswith((b"GIF87a", b"GIF89a"))
    if extension == "webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if extension == "webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if extension in {"mp4", "mov", "m4v"}:
        return b"ftyp" in header[4:16]

    return False
