from ..database import get_connection, insert_and_get_id
from ..models import default_content_format, truncate_content_for_platform
from .clock import app_now_string


def get_all_posts(filters=None):
    filters = filters or {}
    query = "SELECT * FROM posts WHERE 1=1"
    params = []

    if filters.get("status"):
        query += " AND status = ?"
        params.append(filters["status"])

    if filters.get("platform"):
        query += " AND platform = ?"
        params.append(filters["platform"])

    if filters.get("source_type"):
        query += " AND source_type = ?"
        params.append(filters["source_type"])

    if filters.get("search"):
        query += " AND (LOWER(title) LIKE ? OR LOWER(content) LIKE ? OR LOWER(hashtags) LIKE ?)"
        term = f"%{filters['search'].lower()}%"
        params.extend([term, term, term])

    query += " ORDER BY COALESCE(scheduled_at, created_at) ASC"

    with get_connection() as conn:
        return conn.execute(query, params).fetchall()


def get_post(post_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()


def create_post(post):
    with get_connection() as conn:
        post_id = insert_and_get_id(
            conn,
            """
            INSERT INTO posts (title, content, hashtags, platform, content_format, rss_item_id, source_type, scheduled_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                post.title,
                post.content,
                post.hashtags,
                post.platform,
                post.content_format,
                post.rss_item_id,
                post.source_type,
                post.scheduled_at,
                post.status,
            ),
        )

    add_log(post_id, "INFO", f"Post created with status {post.status}.")
    return post_id


def update_post(post_id, post):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE posts
            SET title = ?, content = ?, hashtags = ?, platform = ?, content_format = ?, scheduled_at = ?,
                status = ?, source_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                post.title,
                post.content,
                post.hashtags,
                post.platform,
                post.content_format,
                post.scheduled_at,
                post.status,
                post.source_type,
                post_id,
            ),
        )

    add_log(post_id, "INFO", f"Post updated with status {post.status}.")


def clone_post_to_platforms(post_id, platforms):
    source = get_post(post_id)
    if source is None:
        return []

    requested_platforms = [platform for platform in platforms if platform and platform != source["platform"]]
    if not requested_platforms:
        return []

    created = []
    with get_connection() as conn:
        media_rows = conn.execute(
            "SELECT filename, original_filename, media_type, public_url FROM media_assets WHERE post_id = ? ORDER BY id ASC",
            (post_id,),
        ).fetchall()
        schedule_rows = conn.execute(
            "SELECT scheduled_at FROM post_schedules WHERE post_id = ? ORDER BY scheduled_at ASC",
            (post_id,),
        ).fetchall()

        for platform in requested_platforms:
            content_format = default_content_format(platform)
            content = truncate_content_for_platform(platform, source["content"], source["hashtags"])
            existing = conn.execute(
                """
                SELECT id FROM posts
                WHERE rss_item_id IS NULL
                  AND platform = ?
                  AND title = ?
                  AND content = ?
                LIMIT 1
                """,
                (platform, source["title"], content),
            ).fetchone()
            if existing:
                continue
            cloned_post_id = insert_and_get_id(
                conn,
                """
                INSERT INTO posts (
                    title, content, hashtags, platform, content_format,
                    rss_item_id, source_type, scheduled_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source["title"],
                    content,
                    source["hashtags"],
                    platform,
                    content_format,
                    None,
                    source["source_type"],
                    source["scheduled_at"],
                    "Draft",
                ),
            )
            for media in media_rows:
                conn.execute(
                    """
                    INSERT INTO media_assets (post_id, filename, original_filename, media_type, public_url)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        cloned_post_id,
                        media["filename"],
                        media["original_filename"],
                        media["media_type"],
                        media["public_url"],
                    ),
                )
            for schedule in schedule_rows:
                conn.execute(
                    "INSERT INTO post_schedules (post_id, scheduled_at, status) VALUES (?, ?, 'Scheduled')",
                    (cloned_post_id, schedule["scheduled_at"]),
                )
            conn.execute(
                "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
                (cloned_post_id, "INFO", f"Manual post cloned from #{post_id} for {platform}."),
            )
            created.append(cloned_post_id)

    return created


def update_post_text(post_id, title, content, hashtags):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE posts
            SET title = ?, content = ?, hashtags = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (title, content, hashtags, post_id),
        )

    add_log(post_id, "INFO", "Post text updated from calendar quick editor.")


def move_post_schedule_date(post_id, scheduled_at):
    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET scheduled_at = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (scheduled_at, post_id),
        )

    add_log(post_id, "INFO", f"Post main schedule moved to {scheduled_at}.")


def delete_post(post_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))

    add_log(None, "INFO", f"Post #{post_id} deleted.")


def get_due_posts():
    now = app_now_string()
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT * FROM posts
            WHERE status = 'Scheduled'
              AND scheduled_at IS NOT NULL
              AND scheduled_at <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM post_schedules
                  WHERE post_schedules.post_id = posts.id
              )
            ORDER BY scheduled_at ASC
            """,
            (now,),
        ).fetchall()


def mark_post_status(post_id, status):
    with get_connection() as conn:
        conn.execute(
            "UPDATE posts SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, post_id),
        )


def add_log(post_id, level, message):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
            (post_id, level, message),
        )


def get_logs():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT logs.*, posts.title AS post_title
            FROM logs
            LEFT JOIN posts ON posts.id = logs.post_id
            ORDER BY logs.created_at DESC, logs.id DESC
            LIMIT 100
            """
        ).fetchall()
