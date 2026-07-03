from ..database import get_connection
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
            SELECT rss_items.*, rss_feeds.name AS feed_name
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
