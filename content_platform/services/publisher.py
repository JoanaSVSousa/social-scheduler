import os
from datetime import datetime

from ..models import FORMAT_MEDIA_RULES
from .media import get_media_for_post
from .media_optimizer import prepare_media_for_publish
from .platform_publishers import is_platform_publishable, publish_to_platform
from .scheduler import add_log, get_due_posts, get_post, mark_post_status
from .schedules import get_due_schedules, has_pending_schedules, mark_schedule_status
from .clock import app_minutes_ago_string, app_now, app_now_string


DEFAULT_PUBLICATION_LOOKBACK_MINUTES = 1440


def process_publication_queue():
    checked_at = app_now_string()
    not_before = _publication_not_before()
    due_posts = get_due_posts(not_before=not_before)
    due_schedules = get_due_schedules(not_before=not_before)
    published = 0

    for schedule in due_schedules:
        delay = _schedule_delay_minutes(schedule["scheduled_at"])
        result = publish_post_by_id(
            schedule["post_id"],
            _scheduled_reason("Scheduled recycled publish", schedule["scheduled_at"], checked_at, delay),
            mark_post_published=False,
        )
        if result["ok"]:
            mark_schedule_status(schedule["id"], "Published")
            if not has_pending_schedules(schedule["post_id"]):
                mark_post_status(schedule["post_id"], "Published")
            published += 1
        elif not result.get("skipped"):
            mark_schedule_status(schedule["id"], "Failed")
            if not has_pending_schedules(schedule["post_id"]):
                mark_post_status(schedule["post_id"], "Failed")

    for post in due_posts:
        delay = _schedule_delay_minutes(post["scheduled_at"])
        result = publish_post(
            post,
            _scheduled_reason("Scheduled publish", post["scheduled_at"], checked_at, delay),
        )
        if result["ok"]:
            published += 1

    if not due_posts and not due_schedules:
        window = not_before or "unlimited"
        add_log(None, "INFO", f"Publication queue checked at {checked_at}. No posts due since {window}.")

    return published


def _publication_not_before():
    value = os.environ.get("PUBLICATION_LOOKBACK_MINUTES", str(DEFAULT_PUBLICATION_LOOKBACK_MINUTES)).strip()
    if not value:
        return None
    try:
        minutes = int(value)
    except ValueError:
        return None
    if minutes <= 0:
        return None
    return app_minutes_ago_string(minutes)


def _scheduled_reason(label, scheduled_at, checked_at, delay_minutes):
    delay_text = ""
    if delay_minutes is not None:
        delay_text = f" Delay: {delay_minutes} minute(s)."
    return f"{label} due at {scheduled_at}; queue checked at {checked_at}.{delay_text}"


def _schedule_delay_minutes(scheduled_at):
    try:
        scheduled_time = datetime.fromisoformat(str(scheduled_at).replace(" ", "T")[:16])
    except (TypeError, ValueError):
        return None
    delay = app_now().replace(tzinfo=None) - scheduled_time
    return max(0, int(delay.total_seconds() // 60))


def publish_post_now(post_id):
    return publish_post_by_id(post_id, "Manual publish requested from Posts page.")


def publish_post_by_id(post_id, reason, mark_post_published=True):
    post = get_post(post_id)
    if post is None:
        return {"ok": False, "message": "Post not found."}
    return publish_post(post, reason, mark_post_published=mark_post_published)


def publish_post(post, reason, mark_post_published=True):
    if not is_platform_publishable(post["platform"]):
        message = f"Real API publishing is not implemented yet for {post['platform']}."
        add_log(post["id"], "INFO", f"{reason} Skipped. {message}")
        return {"ok": False, "skipped": True, "message": message, "post_id": post["id"]}
    try:
        uri = _publish_post(post, reason, mark_post_published=mark_post_published)
    except Exception as exc:
        if mark_post_published:
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


def _publish_post(post, reason, mark_post_published=True):
    media_items = prepare_media_for_publish(get_media_for_post(post["id"]))
    _validate_media_requirements(post, media_items)
    uri = publish_to_platform(post, media_items)
    if mark_post_published:
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
