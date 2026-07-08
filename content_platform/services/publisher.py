from .media import get_media_for_post
from .platform_publishers import publish_to_platform
from .scheduler import add_log, get_due_posts, get_post, mark_post_status
from .schedules import get_due_schedules, mark_schedule_status


def process_publication_queue():
    due_posts = get_due_posts()
    due_schedules = get_due_schedules()
    published = 0

    for schedule in due_schedules:
        result = publish_post_by_id(schedule["post_id"], f"Scheduled recycled publish due at {schedule['scheduled_at']}.")
        if result["ok"]:
            mark_schedule_status(schedule["id"], "Published")
            published += 1
        else:
            mark_schedule_status(schedule["id"], "Failed")

    for post in due_posts:
        result = publish_post(post, "Scheduled publish due now.")
        if result["ok"]:
            published += 1

    if not due_posts and not due_schedules:
        add_log(None, "INFO", "Publication queue checked. No posts due.")

    return published


def publish_post_now(post_id):
    return publish_post_by_id(post_id, "Manual publish requested from Posts page.")


def publish_post_by_id(post_id, reason):
    post = get_post(post_id)
    if post is None:
        return {"ok": False, "message": "Post not found."}
    return publish_post(post, reason)


def publish_post(post, reason):
    try:
        uri = _publish_post(post, reason)
    except Exception as exc:
        mark_post_status(post["id"], "Failed")
        add_log(post["id"], "ERROR", f"{reason} Publication failed: {exc}")
        return {"ok": False, "message": str(exc), "post_id": post["id"]}
    return {"ok": True, "message": uri, "post_id": post["id"]}


def publish_rss_group_now(posts):
    published = 0
    failed = 0
    messages = []
    for post in posts:
        result = publish_post(post, "Manual publish requested for RSS article group.")
        if result["ok"]:
            published += 1
        else:
            failed += 1
            messages.append(f"{post['platform']}: {result['message']}")
    return {"published": published, "failed": failed, "messages": messages}


def _publish_post(post, reason):
    media_items = get_media_for_post(post["id"])
    uri = publish_to_platform(post, media_items)
    mark_post_status(post["id"], "Published")
    add_log(
        post["id"],
        "SUCCESS",
        f"{reason} Published to {post['platform']} with {len(media_items)} media asset(s). Result: {uri}",
    )
    return uri
