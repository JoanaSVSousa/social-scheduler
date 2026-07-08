from datetime import datetime

from ..database import get_connection, insert_and_get_id


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


def delete_post(post_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM posts WHERE id = ?", (post_id,))

    add_log(None, "INFO", f"Post #{post_id} deleted.")


def get_due_posts():
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
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
