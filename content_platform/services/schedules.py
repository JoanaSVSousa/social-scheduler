from ..database import get_connection
from .clock import app_now_string


def replace_schedules(post_id, schedule_dates):
    with get_connection() as conn:
        conn.execute("DELETE FROM post_schedules WHERE post_id = ?", (post_id,))
        for scheduled_at in _clean_dates(schedule_dates):
            conn.execute(
                "INSERT INTO post_schedules (post_id, scheduled_at, status) VALUES (?, ?, 'Scheduled')",
                (post_id, scheduled_at),
            )


def get_schedules_for_post(post_id):
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM post_schedules WHERE post_id = ? ORDER BY scheduled_at ASC",
            (post_id,),
        ).fetchall()


def get_schedules_for_posts(post_ids):
    if not post_ids:
        return {}

    placeholders = ",".join("?" for _ in post_ids)
    with get_connection() as conn:
        rows = conn.execute(
            f"""
            SELECT * FROM post_schedules
            WHERE post_id IN ({placeholders})
            ORDER BY scheduled_at ASC
            """,
            post_ids,
        ).fetchall()

    schedules_by_post = {post_id: [] for post_id in post_ids}
    for row in rows:
        schedules_by_post[row["post_id"]].append(row)
    return schedules_by_post


def get_due_schedules():
    now = app_now_string()
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT post_schedules.*, posts.title, posts.platform
            FROM post_schedules
            JOIN posts ON posts.id = post_schedules.post_id
            WHERE post_schedules.status = 'Scheduled'
              AND post_schedules.scheduled_at <= ?
            ORDER BY post_schedules.scheduled_at ASC
            """,
            (now,),
        ).fetchall()


def mark_schedule_status(schedule_id, status):
    published_at = app_now_string() if status == "Published" else None
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE post_schedules
            SET status = ?, published_at = ?
            WHERE id = ?
            """,
            (status, published_at, schedule_id),
        )


def get_schedule(schedule_id):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM post_schedules WHERE id = ?", (schedule_id,)).fetchone()


def move_schedule_date(schedule_id, scheduled_at):
    with get_connection() as conn:
        conn.execute(
            "UPDATE post_schedules SET scheduled_at = ? WHERE id = ?",
            (scheduled_at, schedule_id),
        )


def _clean_dates(schedule_dates):
    seen = set()
    cleaned = []
    for scheduled_at in schedule_dates:
        scheduled_at = scheduled_at.strip()
        if not scheduled_at or scheduled_at in seen:
            continue
        seen.add(scheduled_at)
        cleaned.append(scheduled_at)
    return cleaned
