from ..database import get_connection
from ..models import default_content_format


def list_rss_groups():
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                rss_items.id,
                rss_items.title,
                rss_items.url,
                rss_items.content_type,
                rss_items.created_at,
                rss_feeds.name AS feed_name,
                COUNT(posts.id) AS post_count,
                SUM(CASE WHEN posts.status = 'Draft' THEN 1 ELSE 0 END) AS draft_count,
                GROUP_CONCAT(posts.platform, ', ') AS platforms
            FROM rss_items
            JOIN rss_feeds ON rss_feeds.id = rss_items.feed_id
            LEFT JOIN posts ON posts.rss_item_id = rss_items.id
            GROUP BY rss_items.id
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
            cursor = conn.execute(
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
            post_id = cursor.lastrowid
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
