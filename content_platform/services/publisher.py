from .media import get_media_for_post
from .scheduler import add_log, get_due_posts, mark_post_status
from .schedules import get_due_schedules, mark_schedule_status


def process_publication_queue():
    due_posts = get_due_posts()
    due_schedules = get_due_schedules()
    published = 0

    for schedule in due_schedules:
        try:
            media_items = get_media_for_post(schedule["post_id"])
            mark_schedule_status(schedule["id"], "Published")
            add_log(
                schedule["post_id"],
                "SUCCESS",
                (
                    f"Published recycled schedule for {schedule['platform']} at {schedule['scheduled_at']} "
                    f"with {len(media_items)} media asset(s)."
                ),
            )
            published += 1
        except Exception as exc:
            mark_schedule_status(schedule["id"], "Failed")
            add_log(schedule["post_id"], "ERROR", f"Scheduled publication failed: {exc}")

    for post in due_posts:
        try:
            # Future API calls will live here. The MVP simulates a successful publish.
            media_items = get_media_for_post(post["id"])
            mark_post_status(post["id"], "Published")
            add_log(post["id"], "SUCCESS", f"Published to {post['platform']} with {len(media_items)} media asset(s).")
            published += 1
        except Exception as exc:
            mark_post_status(post["id"], "Failed")
            add_log(post["id"], "ERROR", f"Publication failed: {exc}")

    if not due_posts and not due_schedules:
        add_log(None, "INFO", "Publication queue checked. No posts due.")

    return published
