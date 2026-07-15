from ..database import get_connection, insert_and_get_id
from ..models import PLATFORM_CONTENT_FORMATS, default_content_format
from .media import delete_media


def list_rss_groups():
    with get_connection() as conn:
        platform_aggregation = (
            "STRING_AGG(posts.platform, ', ' ORDER BY posts.platform)"
            if conn.dialect == "postgres"
            else "GROUP_CONCAT(posts.platform, ', ')"
        )
        return conn.execute(
            f"""
            SELECT
                rss_items.id,
                rss_items.title,
                rss_items.url,
                rss_items.content_type,
                rss_items.created_at,
                rss_feeds.name AS feed_name,
                COUNT(posts.id) AS post_count,
                SUM(CASE WHEN posts.status = 'Draft' THEN 1 ELSE 0 END) AS draft_count,
                {platform_aggregation} AS platforms
            FROM rss_items
            JOIN rss_feeds ON rss_feeds.id = rss_items.feed_id
            LEFT JOIN posts ON posts.rss_item_id = rss_items.id
            GROUP BY rss_items.id, rss_feeds.name
            ORDER BY rss_items.created_at DESC
            """
        ).fetchall()


def get_rss_group(rss_item_id):
    with get_connection() as conn:
        item = conn.execute(
            """
            SELECT rss_items.*, rss_feeds.name AS feed_name, rss_feeds.default_hashtags
            FROM rss_items
            JOIN rss_feeds ON rss_feeds.id = rss_items.feed_id
            WHERE rss_items.id = ?
            """,
            (rss_item_id,),
        ).fetchone()
        posts = conn.execute(
            """
            SELECT * FROM posts
            WHERE rss_item_id = ?
            ORDER BY platform ASC
            """,
            (rss_item_id,),
        ).fetchall()
    return item, posts


def sync_rss_group_platforms(rss_item_id, selected_platforms):
    item, posts = get_rss_group(rss_item_id)
    if item is None:
        return None, []

    selected_platforms = set(selected_platforms)
    existing_by_platform = {post["platform"]: post for post in posts}

    with get_connection() as conn:
        for post in posts:
            if post["platform"] not in selected_platforms and post["status"] != "Published":
                conn.execute("DELETE FROM posts WHERE id = ?", (post["id"],))
                conn.execute(
                    "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
                    (None, "INFO", f"RSS article version removed for {post['platform']}."),
                )

        for platform in selected_platforms:
            if platform in existing_by_platform:
                continue
            post_id = insert_and_get_id(
                conn,
                """
                INSERT INTO posts (
                    title, content, hashtags, platform, content_format,
                    rss_item_id, source_type, scheduled_at, status
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["title"][:120],
                    f"Source: {item['url']}",
                    item["default_hashtags"] or "",
                    platform,
                    default_content_format(platform),
                    rss_item_id,
                    item["content_type"],
                    "",
                    "Draft",
                ),
            )
            conn.execute(
                "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
                (post_id, "INFO", f"RSS article version created for {platform}."),
            )

        first_post = conn.execute(
            """
            SELECT id FROM posts
            WHERE rss_item_id = ?
            ORDER BY id ASC
            LIMIT 1
            """,
            (rss_item_id,),
        ).fetchone()
        conn.execute(
            "UPDATE rss_items SET post_id = ? WHERE id = ?",
            (first_post["id"] if first_post else None, rss_item_id),
        )

    return get_rss_group(rss_item_id)


def update_rss_group_posts(post_updates):
    with get_connection() as conn:
        for update in post_updates:
            conn.execute(
                """
                UPDATE posts
                SET title = ?, content = ?, hashtags = ?, content_format = ?,
                    status = ?, scheduled_at = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    update["title"],
                    update["content"],
                    update["hashtags"],
                    update["content_format"],
                    update["status"],
                    update["scheduled_at"],
                    update["post_id"],
                ),
            )
            conn.execute(
                "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
                (update["post_id"], "INFO", "RSS article version updated from grouped editor."),
            )


def update_rss_group_content_type(rss_item_id, content_type):
    with get_connection() as conn:
        conn.execute(
            "UPDATE rss_items SET content_type = ? WHERE id = ?",
            (content_type, rss_item_id),
        )
        conn.execute(
            """
            UPDATE posts
            SET source_type = ?, updated_at = CURRENT_TIMESTAMP
            WHERE rss_item_id = ?
            """,
            (content_type, rss_item_id),
        )
        conn.execute(
            "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
            (None, "INFO", f"RSS article group #{rss_item_id} marked as {content_type}."),
        )


def update_rss_group_library_fields(rss_item_ids, source_type="", content_format=""):
    rss_item_ids = [int(item_id) for item_id in rss_item_ids if str(item_id).isdigit()]
    if not rss_item_ids:
        return 0

    updated = 0
    with get_connection() as conn:
        for rss_item_id in rss_item_ids:
            if source_type:
                conn.execute(
                    "UPDATE rss_items SET content_type = ? WHERE id = ?",
                    (source_type, rss_item_id),
                )
                conn.execute(
                    """
                    UPDATE posts
                    SET source_type = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE rss_item_id = ?
                    """,
                    (source_type, rss_item_id),
                )
                updated += 1

            if content_format:
                posts = conn.execute(
                    "SELECT id, platform FROM posts WHERE rss_item_id = ?",
                    (rss_item_id,),
                ).fetchall()
                changed_any = False
                for post in posts:
                    if content_format not in PLATFORM_CONTENT_FORMATS.get(post["platform"], []):
                        continue
                    conn.execute(
                        """
                        UPDATE posts
                        SET content_format = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (content_format, post["id"]),
                    )
                    changed_any = True
                if changed_any and not source_type:
                    updated += 1

            conn.execute(
                "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
                (None, "INFO", f"RSS article group #{rss_item_id} updated from Posts page."),
            )

    return updated


def move_rss_group_main_schedule(rss_item_id, old_scheduled_at, new_scheduled_at):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE posts
            SET scheduled_at = ?, updated_at = CURRENT_TIMESTAMP
            WHERE rss_item_id = ?
              AND scheduled_at = ?
            """,
            (new_scheduled_at, rss_item_id, old_scheduled_at),
        )


def move_rss_group_recycled_schedule(rss_item_id, old_scheduled_at, new_scheduled_at):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE post_schedules
            SET scheduled_at = ?
            WHERE scheduled_at = ?
              AND post_id IN (
                  SELECT id FROM posts WHERE rss_item_id = ?
              )
            """,
            (new_scheduled_at, old_scheduled_at, rss_item_id),
        )


def move_rss_group_schedule_occurrence(rss_item_id, old_scheduled_at, new_scheduled_at):
    move_rss_group_main_schedule(rss_item_id, old_scheduled_at, new_scheduled_at)
    move_rss_group_recycled_schedule(rss_item_id, old_scheduled_at, new_scheduled_at)


def delete_rss_group(rss_item_id):
    with get_connection() as conn:
        post_rows = conn.execute("SELECT id FROM posts WHERE rss_item_id = ?", (rss_item_id,)).fetchall()
        post_ids = [row["id"] for row in post_rows]
        media_rows = []
        if post_ids:
            placeholders = ",".join("?" for _ in post_ids)
            media_rows = conn.execute(
                f"SELECT id FROM media_assets WHERE post_id IN ({placeholders})",
                post_ids,
            ).fetchall()

    for media in media_rows:
        delete_media(media["id"])

    with get_connection() as conn:
        conn.execute("DELETE FROM posts WHERE rss_item_id = ?", (rss_item_id,))
        conn.execute("DELETE FROM rss_items WHERE id = ?", (rss_item_id,))
        conn.execute(
            "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
            (None, "INFO", f"RSS article group #{rss_item_id} deleted."),
        )
