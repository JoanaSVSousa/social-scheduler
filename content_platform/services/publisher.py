from ..models import FORMAT_MEDIA_RULES
from .media import get_media_for_post
from .media_optimizer import prepare_media_for_publish
from .platform_publishers import is_platform_publishable, publish_to_platform
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
        elif not result.get("skipped"):
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
    if not is_platform_publishable(post["platform"]):
        message = f"Real API publishing is not implemented yet for {post['platform']}."
        add_log(post["id"], "INFO", f"{reason} Skipped. {message}")
        return {"ok": False, "skipped": True, "message": message, "post_id": post["id"]}
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
    skipped = 0
    messages = []
    for post in posts:
        if not is_platform_publishable(post["platform"]):
            skipped += 1
            message = f"{post['platform']}: real API publishing is not implemented yet."
            messages.append(message)
            add_log(post["id"], "INFO", f"Manual publish requested for RSS article group. Skipped. {message}")
            continue
        result = publish_post(post, "Manual publish requested for RSS article group.")
        if result["ok"]:
            published += 1
        else:
            failed += 1
            messages.append(f"{post['platform']}: {result['message']}")
    return {"published": published, "failed": failed, "skipped": skipped, "messages": messages}


def _publish_post(post, reason):
    media_items = prepare_media_for_publish(get_media_for_post(post["id"]))
    _validate_media_requirements(post, media_items)
    uri = publish_to_platform(post, media_items)
    mark_post_status(post["id"], "Published")
    add_log(
        post["id"],
        "SUCCESS",
        f"{reason} Published to {post['platform']} with {len(media_items)} media asset(s). Result: {uri}",
    )
    return uri


def _validate_media_requirements(post, media_items):
    content_format = post["content_format"] or ""
    rules = FORMAT_MEDIA_RULES.get(content_format)
    if not rules:
        return

    allowed_media_types = rules.get("allowed_media_types", [])
    media_types = [item.get("media_type") for item in media_items if hasattr(item, "get")]
    matching_media = [media_type for media_type in media_types if media_type in allowed_media_types]

    if rules.get("media_required") and not matching_media:
        required = " or ".join(allowed_media_types) if allowed_media_types else "media"
        raise ValueError(f"{post['platform']} {content_format} requires {required} media before publishing.")

    if media_items and allowed_media_types and not matching_media:
        allowed = " or ".join(allowed_media_types)
        raise ValueError(f"{post['platform']} {content_format} only accepts {allowed} media.")
