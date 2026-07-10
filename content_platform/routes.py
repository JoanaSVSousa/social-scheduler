from calendar import Calendar, month_name
from datetime import datetime, timedelta
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for

from .models import (
    FORMAT_MEDIA_GUIDES,
    FORMAT_MEDIA_RULES,
    PLATFORM_CONTENT_FORMATS,
    PLATFORM_MEDIA_GUIDES,
    PLATFORMS,
    PLATFORM_CONTENT_LIMITS,
    STATUSES,
    Post,
    content_limit_for_post,
    default_content_format,
    truncate_content_for_platform,
)
from .security import validate_csrf
from .auth import is_logged_in, login_required, verify_admin_credentials
from .services.analytics import build_platform_counts, build_status_counts
from .services.media import delete_media, get_media_for_post, get_media_for_posts, save_media_files
from .services.publisher import process_publication_queue, publish_post_now, publish_rss_group_now
from .services.rich_text import compose_publication_text
from .services.rss import (
    check_all_feeds,
    create_feed,
    delete_feed,
    get_feed,
    list_feeds,
    refresh_rss_content_types,
    update_feed,
)
from .services.rss_groups import (
    delete_rss_group,
    get_rss_group,
    list_rss_groups,
    move_rss_group_schedule_occurrence,
    sync_rss_group_platforms,
    update_rss_group_content_type,
    update_rss_group_posts,
)
from .services.schedules import (
    get_schedule,
    get_schedules_for_post,
    get_schedules_for_posts,
    move_schedule_date,
    replace_schedules,
)
from .services.scheduler import (
    clone_post_to_platforms,
    create_post,
    delete_post,
    add_log,
    get_all_posts,
    get_logs,
    get_post,
    move_post_schedule_date,
    update_post_text,
    update_post,
)
from .services.social_accounts import (
    SOCIAL_ACCOUNT_SCHEMAS,
    credential_field_names,
    credential_summary,
    delete_social_account,
    decrypt_credentials_for_publisher,
    public_credential_values,
    save_social_account,
    social_accounts_by_platform,
)
from .services.squared_feeds import SQUARED_FEEDS


bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    refresh_rss_content_types()
    posts = get_all_posts()
    post_ids = [post["id"] for post in posts]
    media_by_post = get_media_for_posts(post_ids)
    schedules_by_post = get_schedules_for_posts(post_ids)
    post_rows = _aggregate_posts_for_library(posts, media_by_post, schedules_by_post)
    calendar_context = _build_dashboard_calendar(posts, schedules_by_post)
    return render_template(
        "dashboard.html",
        posts=post_rows[:8],
        media_by_post=media_by_post,
        schedules_by_post=schedules_by_post,
        calendar_context=calendar_context,
        status_counts=build_status_counts(posts),
        platform_counts=build_platform_counts(posts),
    )


@bp.route("/settings/social-accounts")
@login_required
def social_account_settings():
    posts = get_all_posts()
    social_accounts = social_accounts_by_platform()
    return render_template(
        "social_accounts.html",
        platform_counts=build_platform_counts(posts),
        social_accounts=social_accounts,
        social_credential_summaries={
            platform: credential_summary(account) for platform, account in social_accounts.items()
        },
        social_public_credentials={
            platform: public_credential_values(account) for platform, account in social_accounts.items()
        },
        social_account_schemas=SOCIAL_ACCOUNT_SCHEMAS,
        platforms=PLATFORMS,
    )


@bp.route("/posts")
def posts():
    refresh_rss_content_types()
    source_types = ["Regular", "News"]
    sort_options = _post_sort_options()
    filters = {
        "status": request.args.get("status", ""),
        "platform": request.args.get("platform", ""),
        "source_type": request.args.get("source_type", ""),
        "search": request.args.get("search", ""),
        "sort": request.args.get("sort", "scheduled_asc"),
    }
    if filters["status"] and filters["status"] not in STATUSES:
        filters["status"] = ""
    if filters["platform"] and filters["platform"] not in PLATFORMS:
        filters["platform"] = ""
    if filters["source_type"] and filters["source_type"] not in source_types:
        filters["source_type"] = ""
    if filters["sort"] not in sort_options:
        filters["sort"] = "scheduled_asc"
    filtered_posts = get_all_posts(filters)
    media_by_post = get_media_for_posts([post["id"] for post in filtered_posts])
    schedules_by_post = get_schedules_for_posts([post["id"] for post in filtered_posts])
    post_rows = _aggregate_posts_for_library(filtered_posts, media_by_post, schedules_by_post)
    post_rows = _sort_post_rows(post_rows, filters["sort"])
    return render_template(
        "posts.html",
        posts=post_rows,
        media_by_post=media_by_post,
        schedules_by_post=schedules_by_post,
        statuses=STATUSES,
        platforms=PLATFORMS,
        source_types=source_types,
        sort_options=sort_options,
        filters=filters,
    )


def _aggregate_posts_for_library(posts, media_by_post, schedules_by_post):
    rows = []
    rss_groups = {}

    for post in posts:
        post_data = dict(post)
        if not post_data.get("rss_item_id"):
            post_data["is_rss_group"] = False
            post_data["sort_scheduled_at"] = _earliest_schedule_value(post_data, schedules_by_post.get(post_data["id"], []))
            post_data["x_manual_url"] = _x_manual_composer_url(post_data)
            rows.append(post_data)
            continue

        group = rss_groups.setdefault(
            post_data["rss_item_id"],
            {
                "id": post_data["id"],
                "rss_item_id": post_data["rss_item_id"],
                "title": post_data["title"],
                "content": post_data["content"],
                "platform": "",
                "content_format": "Multiple versions",
                "status": post_data["status"],
                "source_type": post_data["source_type"],
                "scheduled_at": post_data["scheduled_at"],
                "sort_scheduled_at": _earliest_schedule_value(post_data, schedules_by_post.get(post_data["id"], [])),
                "created_at": post_data["created_at"],
                "hashtags": post_data["hashtags"],
                "is_rss_group": True,
                "platforms": [],
                "statuses": [],
                "media_total": 0,
                "schedule_total": 0,
                "x_manual_url": "",
            },
        )
        group["platforms"].append(post_data["platform"])
        group["statuses"].append(post_data["status"])
        group["media_total"] += len(media_by_post.get(post_data["id"], []))
        group["schedule_total"] += len(schedules_by_post.get(post_data["id"], []))
        post_schedule = _earliest_schedule_value(post_data, schedules_by_post.get(post_data["id"], []))
        if post_schedule and (not group["sort_scheduled_at"] or post_schedule < group["sort_scheduled_at"]):
            group["sort_scheduled_at"] = post_schedule
            group["scheduled_at"] = post_schedule
        if post_data["created_at"] and post_data["created_at"] < group["created_at"]:
            group["created_at"] = post_data["created_at"]
        if post_data["platform"] == "X":
            group["x_manual_url"] = _x_manual_composer_url(post_data)

    for group in rss_groups.values():
        group["platform"] = ", ".join(sorted(set(group["platforms"])))
        unique_statuses = sorted(set(group["statuses"]))
        group["status"] = unique_statuses[0] if len(unique_statuses) == 1 else "Mixed"
        rows.append(group)

    return rows


def _x_manual_composer_url(post):
    if post.get("platform") != "X":
        return ""
    text = compose_publication_text("X", post.get("content", ""), post.get("hashtags", ""))
    if not text:
        return ""
    return "https://twitter.com/intent/tweet?" + urlencode({"text": text})


def _earliest_schedule_value(post, schedules):
    values = []
    if post["scheduled_at"]:
        values.append(post["scheduled_at"])
    values.extend(schedule["scheduled_at"] for schedule in schedules if schedule["scheduled_at"])
    return min(values) if values else ""


def _sort_post_rows(rows, sort_key):
    sort_key = sort_key if sort_key in _post_sort_options() else "scheduled_asc"

    if sort_key == "created_desc":
        return sorted(rows, key=lambda row: row["created_at"] or "", reverse=True)
    if sort_key == "created_asc":
        return sorted(rows, key=lambda row: row["created_at"] or "")
    if sort_key == "scheduled_desc":
        scheduled_rows = [row for row in rows if row["sort_scheduled_at"]]
        unscheduled_rows = [row for row in rows if not row["sort_scheduled_at"]]
        return sorted(scheduled_rows, key=lambda row: row["sort_scheduled_at"], reverse=True) + unscheduled_rows
    return sorted(rows, key=lambda row: (row["sort_scheduled_at"] == "", row["sort_scheduled_at"] or ""))


def _post_sort_options():
    return {
        "scheduled_asc": "Scheduled date: soonest first",
        "scheduled_desc": "Scheduled date: latest first",
        "created_desc": "Added date: newest first",
        "created_asc": "Added date: oldest first",
    }


def _build_dashboard_calendar(posts, schedules_by_post):
    today = datetime.now()
    year = _int_arg("year", today.year)
    month = _int_arg("month", today.month)
    if month < 1 or month > 12:
        year = today.year
        month = today.month

    previous_month = month - 1
    previous_year = year
    if previous_month == 0:
        previous_month = 12
        previous_year -= 1

    next_month = month + 1
    next_year = year
    if next_month == 13:
        next_month = 1
        next_year += 1

    events_by_day = _calendar_events_for_month(posts, schedules_by_post, year, month)
    weeks = []
    for week in Calendar(firstweekday=0).monthdatescalendar(year, month):
        weeks.append(
            [
                {
                    "date": day,
                    "day": day.day,
                    "is_current_month": day.month == month,
                    "events": events_by_day.get(day.strftime("%Y-%m-%d"), []),
                }
                for day in week
            ]
        )

    return {
        "label": f"{month_name[month]} {year}",
        "weeks": weeks,
        "previous": {"year": previous_year, "month": previous_month},
        "next": {"year": next_year, "month": next_month},
    }


def _calendar_events_for_month(posts, schedules_by_post, year, month):
    events = {}
    seen = {}
    for post in posts:
        date_values = []
        if post["scheduled_at"]:
            date_values.append({"type": "post", "id": "", "scheduled_at": post["scheduled_at"]})
        date_values.extend(
            {"type": "schedule", "id": item["id"], "scheduled_at": item["scheduled_at"]}
            for item in schedules_by_post.get(post["id"], [])
        )

        for date_item in date_values:
            scheduled_at = date_item["scheduled_at"]
            event_dt = _parse_calendar_datetime(scheduled_at)
            if event_dt is None or event_dt.year != year or event_dt.month != month:
                continue

            group_key = post["rss_item_id"] or post["id"]
            event_key = (group_key, scheduled_at)
            existing = seen.get(event_key)
            if existing:
                if post["platform"] not in existing["platforms"]:
                    existing["platforms"].append(post["platform"])
                    existing["platform"] = ", ".join(sorted(existing["platforms"]))
                continue

            event = {
                "title": post["title"],
                "time": event_dt.strftime("%H:%M"),
                "platform": post["platform"],
                "platforms": [post["platform"]],
                "status": post["status"],
                "url": _edit_url_for_post(post),
                "post_id": post["id"],
                "schedule_id": date_item["id"],
                "event_type": date_item["type"],
                "scheduled_at": scheduled_at,
                "content": post["content"],
                "hashtags": post["hashtags"],
            }
            seen[event_key] = event
            events.setdefault(event_dt.strftime("%Y-%m-%d"), []).append(event)

    for day_events in events.values():
        day_events.sort(key=lambda event: event["time"])

    return events


def _parse_calendar_datetime(value):
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _edit_url_for_post(post):
    if post["rss_item_id"]:
        return url_for("main.edit_rss_article", rss_item_id=post["rss_item_id"])
    return url_for("main.edit_post", post_id=post["id"])


def _publish_group_summary(prefix, result):
    parts = []
    if result.get("published"):
        parts.append(f"Published {result['published']} version(s)")
    if result.get("skipped"):
        parts.append(f"skipped {result['skipped']} unsupported platform(s)")
    if result.get("failed"):
        parts.append(f"{result['failed']} failed")
    message = "; ".join(parts) + ". Check logs."
    return f"{prefix} {message}".strip()


@bp.post("/calendar/posts/<int:post_id>/quick-edit")
def quick_edit_calendar_post(post_id):
    validate_csrf()
    post = get_post(post_id)
    if post is None:
        abort(404)

    title = request.form.get("title", "").strip()[:120]
    hashtags = request.form.get("hashtags", "").strip()[:400]
    content = truncate_content_for_platform(post["platform"], request.form.get("content", ""), hashtags)
    if not title or not content:
        abort(400)

    update_post_text(post_id, title, content, hashtags)
    saved, skipped = save_media_files(post_id, request.files.getlist("media_files"), post["content_format"])
    _flash_media_result(saved, skipped)
    flash("Calendar quick edit saved.", "success")
    return redirect(url_for("main.dashboard"))


@bp.post("/calendar/reschedule")
def reschedule_calendar_event():
    validate_csrf()
    event_type = request.form.get("event_type", "")
    post_id = request.form.get("post_id", "").strip()
    schedule_id = request.form.get("schedule_id", "").strip()
    target_date = request.form.get("target_date", "").strip()
    scheduled_at = request.form.get("scheduled_at", "").strip()

    if not target_date or not scheduled_at:
        abort(400)

    current_dt = _parse_calendar_datetime(_normalize_datetime_value(scheduled_at))
    if current_dt is None:
        abort(400)
    new_scheduled_at = f"{target_date}T{current_dt.strftime('%H:%M')}"
    _normalize_datetime_value(new_scheduled_at)

    if event_type == "schedule":
        if not schedule_id:
            abort(400)
        schedule = get_schedule(int(schedule_id))
        if schedule is None:
            abort(404)
        post = get_post(schedule["post_id"])
        if post and post["rss_item_id"]:
            move_rss_group_schedule_occurrence(post["rss_item_id"], _normalize_datetime_value(scheduled_at), new_scheduled_at)
            add_log(schedule["post_id"], "INFO", f"RSS group schedule occurrence moved to {new_scheduled_at} from calendar.")
        else:
            move_schedule_date(int(schedule_id), new_scheduled_at)
            add_log(schedule["post_id"], "INFO", f"Recycled schedule moved to {new_scheduled_at} from calendar.")
    elif event_type == "post":
        if not post_id:
            abort(400)
        post = get_post(int(post_id))
        if post is None:
            abort(404)
        if post["rss_item_id"]:
            move_rss_group_schedule_occurrence(post["rss_item_id"], _normalize_datetime_value(scheduled_at), new_scheduled_at)
            add_log(post["id"], "INFO", f"RSS group schedule occurrence moved to {new_scheduled_at} from calendar.")
        else:
            move_post_schedule_date(int(post_id), new_scheduled_at)
    else:
        abort(400)

    flash("Schedule moved.", "success")
    return redirect(url_for("main.dashboard"))


def _int_arg(name, fallback):
    try:
        return int(request.args.get(name, fallback))
    except (TypeError, ValueError):
        return fallback


@bp.route("/rss/articles")
@login_required
def rss_articles():
    return render_template("rss_articles.html", groups=list_rss_groups())


@bp.route("/rss/articles/<int:rss_item_id>", methods=["GET", "POST"])
@login_required
def edit_rss_article(rss_item_id):
    item, posts = get_rss_group(rss_item_id)
    if item is None:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        selected_platforms = request.form.getlist("target_platforms")
        if not selected_platforms or any(platform not in PLATFORMS for platform in selected_platforms):
            abort(400)
        item, posts = sync_rss_group_platforms(rss_item_id, selected_platforms)
        content_type = request.form.get("content_type", item["content_type"])
        if content_type not in {"Regular", "News"}:
            abort(400)
        update_rss_group_content_type(rss_item_id, content_type)
        item, posts = get_rss_group(rss_item_id)
        general_status = request.form.get("general_status", "Draft")
        general_values = {
            "title": request.form.get("general_title", "").strip()[:120],
            "content": request.form.get("general_content", "").strip()[:2200],
            "hashtags": request.form.get("general_hashtags", "").strip()[:400],
            "status": general_status,
            "scheduled_at": _datetime_from_form("", "general_scheduled"),
        }
        if general_status not in STATUSES:
            abort(400)
        if not general_values["title"] or not general_values["content"]:
            abort(400)
        general_schedule_dates = _schedule_dates_from_general_form()
        general_media_files = request.files.getlist("general_media_files")
        updates = []
        for post in posts:
            prefix = f"post_{post['id']}_"
            status = _override_or_general(prefix, "status", post["status"], general_values["status"])
            general_content_format = request.form.get(f"general_content_format_{post['id']}", post["content_format"])
            content_format = (
                request.form.get(prefix + "content_format", post["content_format"])
                if _uses_field_override(prefix, "format")
                else general_content_format
            )
            if status not in STATUSES:
                abort(400)
            if content_format not in PLATFORM_CONTENT_FORMATS.get(post["platform"], []):
                abort(400)
            title = _override_or_general(prefix, "title", post["title"], general_values["title"], 120)
            hashtags = _override_or_general(prefix, "hashtags", post["hashtags"], general_values["hashtags"], 400)
            content = _override_or_general(prefix, "content", post["content"], general_values["content"])
            content = truncate_content_for_platform(post["platform"], content, hashtags)
            updates.append(
                {
                    "post_id": post["id"],
                    "title": title,
                    "content": content,
                    "hashtags": hashtags,
                    "content_format": content_format,
                    "status": status,
                    "scheduled_at": _datetime_from_form(prefix) if _uses_field_override(prefix, "schedule") else general_values["scheduled_at"],
                }
            )
            if not updates[-1]["title"] or not updates[-1]["content"]:
                abort(400)

        update_rss_group_posts(updates)
        for post in posts:
            prefix = f"post_{post['id']}_"
            general_content_format = request.form.get(f"general_content_format_{post['id']}", post["content_format"])
            content_format = (
                request.form.get(prefix + "content_format", post["content_format"])
                if _uses_field_override(prefix, "format")
                else general_content_format
            )
            schedule_dates = _schedule_dates_from_prefixed_form(prefix) if _uses_field_override(prefix, "schedule") else general_schedule_dates
            replace_schedules(post["id"], schedule_dates)
            _reset_file_streams(general_media_files)
            saved, skipped = save_media_files(post["id"], general_media_files, content_format)
            _flash_media_result(saved, skipped)
            saved, skipped = save_media_files(
                post["id"],
                request.files.getlist(prefix + "media_files"),
                content_format,
            )
            _flash_media_result(saved, skipped)
        if request.form.get("publish_after_save") == "1":
            _, updated_posts = get_rss_group(rss_item_id)
            result = publish_rss_group_now(updated_posts)
            if result["published"] and not result["failed"] and not result.get("skipped"):
                flash(f"Article versions saved and {result['published']} version(s) published.", "success")
            elif result["published"]:
                flash(_publish_group_summary("Article versions saved.", result), "warning")
            elif result.get("skipped"):
                flash(_publish_group_summary("Article versions saved.", result), "warning")
            else:
                flash("Article versions saved, but publication failed for every version. Check logs.", "warning")
        else:
            flash("Article versions updated.", "success")
        return redirect(url_for("main.edit_rss_article", rss_item_id=rss_item_id))

    schedules_by_post = get_schedules_for_posts([post["id"] for post in posts])
    media_by_post = get_media_for_posts([post["id"] for post in posts])
    general_defaults, editor_meta = _rss_editor_defaults(posts, schedules_by_post)
    return render_template(
        "rss_article_edit.html",
        item=item,
        posts=posts,
        general_defaults=general_defaults,
        editor_meta=editor_meta,
        schedules_by_post=schedules_by_post,
        media_by_post=media_by_post,
        content_formats=PLATFORM_CONTENT_FORMATS,
        media_guides=PLATFORM_MEDIA_GUIDES,
        statuses=STATUSES,
        platforms=PLATFORMS,
        datetime_parts=_datetime_parts,
        format_rules=FORMAT_MEDIA_RULES,
        content_limits=PLATFORM_CONTENT_LIMITS,
        content_limit_for_post=content_limit_for_post,
    )


@bp.route("/posts/new", methods=["GET", "POST"])
def new_post():
    if request.method == "POST":
        validate_csrf()
        post_id = create_post(_post_from_form())
        replace_schedules(post_id, _schedule_dates_from_form())
        saved, skipped = save_media_files(post_id, request.files.getlist("media_files"), request.form.get("content_format", ""))
        _flash_media_result(saved, skipped)
        flash("Post created. You can keep editing or publish it when ready.", "success")
        return redirect(url_for("main.edit_post", post_id=post_id))

    return render_template(
        "post_form.html",
        post=None,
        media=[],
        schedules=[],
        content_formats=PLATFORM_CONTENT_FORMATS,
        format_guides=FORMAT_MEDIA_GUIDES,
        format_rules=FORMAT_MEDIA_RULES,
        content_limits=PLATFORM_CONTENT_LIMITS,
        media_guides=PLATFORM_MEDIA_GUIDES,
        statuses=STATUSES,
        platforms=PLATFORMS,
        action="Create",
        datetime_parts=_datetime_parts,
    )


@bp.route("/posts/<int:post_id>/edit", methods=["GET", "POST"])
def edit_post(post_id):
    post = get_post(post_id)
    if post is None:
        return redirect(url_for("main.posts"))

    if request.method == "POST":
        validate_csrf()
        update_post(post_id, _post_from_form())
        replace_schedules(post_id, _schedule_dates_from_form())
        saved, skipped = save_media_files(post_id, request.files.getlist("media_files"), request.form.get("content_format", ""))
        _flash_media_result(saved, skipped)
        if request.form.get("publish_after_save") == "1":
            result = publish_post_now(post_id)
            if result["ok"]:
                flash("Post saved and published successfully.", "success")
            else:
                flash(f"Post saved, but publication failed: {result['message']}", "warning")
        else:
            flash("Post updated.", "success")
        if request.form.get("add_network_versions") == "1":
            selected_platforms = request.form.getlist("additional_platforms")
            if any(platform not in PLATFORMS for platform in selected_platforms):
                abort(400)
            created = clone_post_to_platforms(post_id, selected_platforms)
            if created:
                flash(f"Created {len(created)} additional network version(s).", "success")
            else:
                flash("No additional network versions were created.", "warning")
        return redirect(url_for("main.edit_post", post_id=post_id))

    return render_template(
        "post_form.html",
        post=post,
        media=get_media_for_post(post_id),
        schedules=get_schedules_for_post(post_id),
        content_formats=PLATFORM_CONTENT_FORMATS,
        format_guides=FORMAT_MEDIA_GUIDES,
        format_rules=FORMAT_MEDIA_RULES,
        content_limits=PLATFORM_CONTENT_LIMITS,
        media_guides=PLATFORM_MEDIA_GUIDES,
        statuses=STATUSES,
        platforms=PLATFORMS,
        action="Update",
        datetime_parts=_datetime_parts,
    )


@bp.post("/media/<int:media_id>/delete")
def remove_media(media_id):
    validate_csrf()
    post_id = request.form.get("post_id")
    delete_media(media_id)
    if post_id:
        return redirect(url_for("main.edit_post", post_id=post_id))
    return redirect(url_for("main.posts"))


@bp.post("/posts/<int:post_id>/delete")
def remove_post(post_id):
    validate_csrf()
    delete_post(post_id)
    return redirect(url_for("main.posts"))


@bp.post("/posts/<int:post_id>/publish-now")
def publish_single_post_now(post_id):
    validate_csrf()
    result = publish_post_now(post_id)
    if result["ok"]:
        flash("Post published successfully.", "success")
    else:
        flash(f"Publication failed: {result['message']}", "warning")
    return redirect(url_for("main.posts"))


@bp.post("/rss/articles/<int:rss_item_id>/delete")
def remove_rss_article(rss_item_id):
    validate_csrf()
    delete_rss_group(rss_item_id)
    flash("RSS article and its network versions deleted.", "success")
    return redirect(url_for("main.posts"))


@bp.post("/rss/articles/<int:rss_item_id>/publish-now")
def publish_rss_article_now(rss_item_id):
    validate_csrf()
    item, posts = get_rss_group(rss_item_id)
    if item is None:
        abort(404)
    result = publish_rss_group_now(posts)
    if result["published"] and not result["failed"] and not result.get("skipped"):
        flash(f"Published {result['published']} version(s).", "success")
    elif result["published"]:
        flash(_publish_group_summary("", result), "warning")
    elif result.get("skipped"):
        flash(_publish_group_summary("", result), "warning")
    else:
        flash("Publication failed for every version. Check logs.", "warning")
    return redirect(url_for("main.posts"))


@bp.post("/queue/process")
def process_queue():
    validate_csrf()
    process_publication_queue()
    return redirect(url_for("main.dashboard"))


@bp.post("/settings/social-accounts/<platform>")
@login_required
def save_social_account_settings(platform):
    validate_csrf()
    if platform not in PLATFORMS:
        abort(404)

    credentials = {field: request.form.get(field, "") for field in credential_field_names(platform)}
    try:
        save_social_account(
            platform,
            request.form.get("account_label", "").strip()[:120],
            request.form.get("account_handle", "").strip()[:120],
            request.form.get("auth_type", "api_keys").strip()[:60] or "api_keys",
            credentials,
        )
    except RuntimeError as exc:
        flash(str(exc), "warning")
    else:
        add_log(None, "INFO", f"Social credentials updated for {platform}.")
        flash(f"{platform} credentials saved securely.", "success")
    return redirect(url_for("main.social_account_settings"))


@bp.post("/settings/social-accounts/<platform>/verify")
@login_required
def verify_social_account_settings(platform):
    validate_csrf()
    if platform not in PLATFORMS:
        abort(404)

    account = decrypt_credentials_for_publisher(platform)
    if not account:
        flash(f"{platform} credentials are not configured yet.", "warning")
        return redirect(url_for("main.social_account_settings"))

    try:
        message = _verify_social_account(account)
    except RuntimeError as exc:
        add_log(None, "ERROR", f"{platform} credential verification failed: {exc}")
        flash(f"{platform} verification failed: {exc}", "warning")
    else:
        add_log(None, "SUCCESS", f"{platform} credential verification passed: {message}")
        flash(f"{platform} verification passed: {message}", "success")
    return redirect(url_for("main.social_account_settings"))


@bp.post("/settings/social-accounts/Threads/connect")
@login_required
def connect_threads_account():
    validate_csrf()
    account = decrypt_credentials_for_publisher("Threads")
    credentials = (account or {}).get("credentials", {})
    app_id = credentials.get("app_id")
    app_secret = credentials.get("app_secret")
    if not app_id or not app_secret:
        flash("Save Threads Meta App ID and Meta App Secret before connecting Threads.", "warning")
        return redirect(url_for("main.social_account_settings"))

    state = secrets.token_urlsafe(24)
    session["threads_oauth_state"] = state
    redirect_uri = url_for("main.threads_oauth_callback", _external=True)
    authorization_url = "https://threads.net/oauth/authorize?" + urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "scope": "threads_basic,threads_content_publish",
            "response_type": "code",
            "state": state,
        }
    )
    return redirect(authorization_url)


@bp.get("/settings/social-accounts/Threads/callback")
@login_required
def threads_oauth_callback():
    if request.args.get("state") != session.pop("threads_oauth_state", ""):
        flash("Threads authorization state did not match. Please try connecting again.", "warning")
        return redirect(url_for("main.social_account_settings"))

    code = request.args.get("code", "").strip()
    if not code:
        flash(request.args.get("error_description") or "Threads did not return an authorization code.", "warning")
        return redirect(url_for("main.social_account_settings"))

    account = decrypt_credentials_for_publisher("Threads")
    credentials = (account or {}).get("credentials", {})
    app_id = credentials.get("app_id")
    app_secret = credentials.get("app_secret")
    if not account or not app_id or not app_secret:
        flash("Threads App ID/App Secret are missing. Save them and connect again.", "warning")
        return redirect(url_for("main.social_account_settings"))

    redirect_uri = url_for("main.threads_oauth_callback", _external=True)
    try:
        token_payload = _exchange_threads_authorization_code(app_id, app_secret, code, redirect_uri)
    except RuntimeError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("main.social_account_settings"))

    access_token = token_payload.get("access_token")
    user_id = str(token_payload.get("user_id") or "")
    if not access_token or not user_id:
        flash("Threads authorization did not return both access_token and user_id.", "warning")
        return redirect(url_for("main.social_account_settings"))

    save_social_account(
        "Threads",
        account.get("account_label", ""),
        account.get("account_handle", ""),
        account.get("auth_type", "threads_api") or "threads_api",
        {"threads_user_id": user_id, "access_token": access_token},
    )
    add_log(None, "INFO", "Threads OAuth connected and credentials updated.")
    flash("Threads connected. User ID and access token saved.", "success")
    return redirect(url_for("main.social_account_settings"))


def _exchange_threads_authorization_code(app_id, app_secret, code, redirect_uri):
    data = urlencode(
        {
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
            "code": code,
        }
    ).encode("utf-8")
    request = Request(
        "https://graph.threads.net/oauth/access_token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Threads token exchange failed {exc.code}: {detail[:400]}") from exc
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Threads token exchange failed: {exc}") from exc


def _verify_social_account(account):
    platform = account["platform"]
    credentials = account["credentials"]
    if platform == "Facebook":
        return _verify_facebook_account(credentials)
    if platform == "Instagram":
        return _verify_instagram_account(credentials)
    raise RuntimeError("Credential verification is currently available for Facebook and Instagram.")


def _verify_facebook_account(credentials):
    page_id = credentials.get("page_id", "")
    access_token = credentials.get("access_token", "")
    if not page_id or not access_token:
        raise RuntimeError("Facebook needs Page ID and Page Access Token.")

    page = _meta_get_json(
        f"https://graph.facebook.com/v20.0/{page_id}",
        {"fields": "id,name", "access_token": access_token},
        "Facebook Page lookup",
    )
    details = [f"Page {page.get('name') or page.get('id')} is readable"]
    token_owner = _meta_get_json(
        "https://graph.facebook.com/v20.0/me",
        {"fields": "id,name", "access_token": access_token},
        "Facebook token owner lookup",
    )
    if str(token_owner.get("id", "")) != str(page_id):
        raise RuntimeError(
            "Token can read the page, but /me identifies it as "
            f"{token_owner.get('name') or token_owner.get('id')}, not the Facebook Page ID {page_id}. "
            "Use the Page Access Token returned inside GET /me/accounts for Squared Potato."
        )
    details.append("token owner matches the page")
    scopes = _meta_token_scopes(credentials)
    if not scopes:
        raise RuntimeError(
            "Page is readable, but publish scopes were not checked because Facebook App ID/App Secret are not saved in this Facebook card."
        )
    missing_scopes = [scope for scope in ["pages_read_engagement", "pages_manage_posts"] if scope not in scopes]
    if scopes and missing_scopes:
        raise RuntimeError(f"Token is readable, but missing scopes: {', '.join(missing_scopes)}.")
    details.append("publish scopes are present")
    return "; ".join(details) + "."


def _verify_instagram_account(credentials):
    instagram_id = credentials.get("instagram_business_id", "")
    access_token = credentials.get("access_token", "")
    if not instagram_id or not access_token:
        raise RuntimeError("Instagram needs Instagram Business ID and Access Token.")

    account = _meta_get_json(
        f"https://graph.facebook.com/v20.0/{instagram_id}",
        {"fields": "id,username", "access_token": access_token},
        "Instagram account lookup",
    )
    return f"Instagram account {account.get('username') or account.get('id')} is readable."


def _meta_token_scopes(credentials):
    app_id = credentials.get("app_id", "")
    app_secret = credentials.get("app_secret", "")
    access_token = credentials.get("access_token", "")
    if not app_id or not app_secret or not access_token:
        return []
    payload = _meta_get_json(
        "https://graph.facebook.com/debug_token",
        {"input_token": access_token, "access_token": f"{app_id}|{app_secret}"},
        "Meta token debug",
    )
    data = payload.get("data") or {}
    scopes = set(data.get("scopes") or [])
    for granular_scope in data.get("granular_scopes") or []:
        scope = granular_scope.get("scope")
        if scope:
            scopes.add(scope)
    if data.get("is_valid") is False:
        raise RuntimeError("Meta says this access token is not valid.")
    return scopes


def _meta_get_json(url, params, endpoint_name):
    request_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(Request(request_url, method="GET"), timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{endpoint_name} error {exc.code}: {_clean_meta_error(detail)}") from exc
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{endpoint_name} failed: {exc}") from exc


def _clean_meta_error(detail):
    try:
        payload = json.loads(detail)
    except json.JSONDecodeError:
        return detail[:400]
    error = payload.get("error") or payload
    pieces = [str(error.get("message") or "Unknown Meta API error")]
    if error.get("code"):
        pieces.append(f"code {error['code']}")
    if error.get("error_subcode"):
        pieces.append(f"subcode {error['error_subcode']}")
    return " ".join(pieces)


@bp.post("/settings/social-accounts/<platform>/delete")
@login_required
def delete_social_account_settings(platform):
    validate_csrf()
    if platform not in PLATFORMS:
        abort(404)
    delete_social_account(platform)
    add_log(None, "INFO", f"Social credentials removed for {platform}.")
    flash(f"{platform} credentials removed.", "success")
    return redirect(url_for("main.social_account_settings"))


@bp.route("/logs")
def logs():
    return render_template("logs.html", logs=get_logs())


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        validate_csrf()
        if verify_admin_credentials(request.form.get("username", ""), request.form.get("password", "")):
            from flask import session

            session["admin_authenticated"] = True
            return redirect(_safe_next_url() or url_for("main.dashboard"))
        flash("Invalid password.", "warning")

    return render_template("login.html")


@bp.post("/logout")
def logout():
    validate_csrf()
    from flask import session

    session.pop("admin_authenticated", None)
    return redirect(url_for("main.dashboard"))


@bp.route("/rss", methods=["GET", "POST"])
@login_required
def rss_feeds():
    if request.method == "POST":
        validate_csrf()
        platforms = request.form.getlist("target_platforms")
        if not platforms or any(platform not in PLATFORMS for platform in platforms):
            abort(400)
        name = request.form["name"].strip()
        url = request.form["url"].strip()
        if not name or len(name) > 120 or not _is_safe_feed_url(url):
            abort(400)
        created = create_feed(
            name,
            url,
            platforms,
            request.form.get("default_hashtags", "").strip(),
        )
        if created:
            flash("RSS feed added.", "success")
        else:
            flash("RSS feed already exists.", "warning")
        return redirect(url_for("main.rss_feeds"))

    return render_template(
        "rss.html",
        feeds=list_feeds(),
        platforms=PLATFORMS,
        is_logged_in=is_logged_in(),
    )


@bp.post("/rss/check")
@login_required
def check_rss():
    validate_csrf()
    result = check_all_feeds(max_entries_per_feed=2)
    flash(
        f"Quick RSS check finished. {result['created']} draft(s) created, "
        f"{result['skipped']} item(s) skipped.",
        "success",
    )
    if result["errors"]:
        flash(f"{len(result['errors'])} RSS error(s) found. Check logs for details.", "warning")
    for error in result["errors"]:
        flash(error, "warning")
    return redirect(url_for("main.rss_feeds"))


@bp.post("/rss/seed-squared")
@login_required
def seed_squared_rss():
    validate_csrf()
    existing_urls = {feed["url"] for feed in list_feeds()}
    created = 0
    skipped = 0

    for feed in SQUARED_FEEDS:
        if feed["url"] in existing_urls:
            skipped += 1
            continue
        if create_feed(feed["name"], feed["url"], feed["platforms"], feed["hashtags"]):
            created += 1
        else:
            skipped += 1

    flash(f"Squared feeds seeded. {created} created, {skipped} already present.", "success")
    return redirect(url_for("main.rss_feeds"))


@bp.route("/rss/<int:feed_id>/edit", methods=["GET", "POST"])
@login_required
def edit_rss_feed(feed_id):
    feed = get_feed(feed_id)
    if feed is None:
        abort(404)

    if request.method == "POST":
        validate_csrf()
        platforms = request.form.getlist("target_platforms")
        name = request.form["name"].strip()
        url = request.form["url"].strip()
        if not platforms or any(platform not in PLATFORMS for platform in platforms):
            abort(400)
        if not name or len(name) > 120 or not _is_safe_feed_url(url):
            abort(400)
        updated = update_feed(
            feed_id,
            name,
            url,
            platforms,
            request.form.get("default_hashtags", "").strip(),
        )
        if updated:
            flash("RSS feed updated.", "success")
            return redirect(url_for("main.rss_feeds"))
        flash("Another RSS feed already uses that URL.", "warning")

    return render_template("rss_feed_form.html", feed=feed, platforms=PLATFORMS)


@bp.post("/rss/<int:feed_id>/delete")
@login_required
def remove_rss_feed(feed_id):
    validate_csrf()
    delete_feed(feed_id)
    flash("RSS feed deleted.", "success")
    return redirect(url_for("main.rss_feeds"))


def _post_from_form():
    title = request.form["title"].strip()
    content = request.form["content"].strip()
    hashtags = request.form.get("hashtags", "").strip()
    platform = request.form["platform"]
    status = request.form["status"]
    content_format = request.form.get("content_format", "").strip() or default_content_format(platform)
    scheduled_at = _datetime_from_form()

    if platform not in PLATFORMS:
        abort(400)
    if status not in STATUSES:
        abort(400)
    if content_format not in PLATFORM_CONTENT_FORMATS.get(platform, []):
        abort(400)
    if not title or len(title) > 120:
        abort(400)
    content = truncate_content_for_platform(platform, content, hashtags)
    if not content:
        abort(400)
    if len(hashtags) > 400:
        abort(400)
    if status == "Scheduled" and not scheduled_at and not request.form.get("schedule_dates", "").strip():
        abort(400)

    return Post(
        title=title,
        content=content,
        hashtags=hashtags,
        platform=platform,
        content_format=content_format,
        scheduled_at=scheduled_at,
        status=status,
        source_type="Regular",
    )


def _flash_media_result(saved, skipped):
    if saved:
        flash(f"{len(saved)} media file(s) attached.", "success")
    if skipped:
        flash("Unsupported file(s) ignored: " + ", ".join(skipped), "warning")


def _rss_editor_defaults(posts, schedules_by_post):
    if not posts:
        return {}, {}

    base_post = posts[0]
    base_schedules = schedules_by_post.get(base_post["id"], [])
    general_defaults = {
        "title": base_post["title"],
        "content": base_post["content"],
        "hashtags": base_post["hashtags"],
        "status": base_post["status"],
        "scheduled_parts": _datetime_parts(base_post["scheduled_at"]),
        "schedule_text": _schedule_text(base_schedules),
    }
    editor_meta = {}
    for post in posts:
        post_schedules = schedules_by_post.get(post["id"], [])
        editor_meta[post["id"]] = {
            "schedule_text": _schedule_text(post_schedules),
            "overrides": {
                "title": post["title"] != general_defaults["title"],
                "content": post["content"] != general_defaults["content"],
                "hashtags": post["hashtags"] != general_defaults["hashtags"],
                "status": post["status"] != general_defaults["status"],
                "schedule": (
                    post["scheduled_at"] != base_post["scheduled_at"]
                    or _schedule_text(post_schedules) != general_defaults["schedule_text"]
                ),
            },
        }
    return general_defaults, editor_meta


def _schedule_text(schedule_items):
    return "\n".join(item["scheduled_at"] for item in schedule_items)


def _override_or_general(prefix, field, current_value, general_value, max_length=None):
    if _uses_field_override(prefix, field):
        value = request.form.get(prefix + field, current_value)
    else:
        value = general_value
    value = (value or "").strip()
    return value[:max_length] if max_length else value


def _uses_field_override(prefix, field):
    return request.form.get(prefix + "override_" + field) == "1"


def _reset_file_streams(files):
    for file in files:
        try:
            file.stream.seek(0)
        except (AttributeError, OSError):
            continue


def _schedule_dates_from_form():
    dates = []
    primary = _datetime_from_form()
    if primary:
        dates.append(primary)
    extra_dates = request.form.get("schedule_dates", "")
    dates.extend(_normalize_datetime_value(line.strip()) for line in extra_dates.splitlines() if line.strip())
    dates.extend(_recurring_dates_from_form(""))
    return dates


def _schedule_dates_from_prefixed_form(prefix):
    dates = []
    primary = _datetime_from_form(prefix)
    if primary:
        dates.append(primary)

    extra_dates = request.form.get(prefix + "schedule_dates", "")
    dates.extend(_normalize_datetime_value(line.strip()) for line in extra_dates.splitlines() if line.strip())
    dates.extend(_recurring_dates_from_form(prefix))
    return dates


def _schedule_dates_from_general_form():
    dates = []
    primary = _datetime_from_form("", "general_scheduled")
    if primary:
        dates.append(primary)

    extra_dates = request.form.get("general_schedule_dates", "")
    dates.extend(_normalize_datetime_value(line.strip()) for line in extra_dates.splitlines() if line.strip())
    dates.extend(_recurring_dates_from_form("general_"))
    return dates


def _recurring_dates_from_form(prefix):
    start = _datetime_from_form(prefix, "repeat")
    count = request.form.get(prefix + "repeat_count", "").strip()
    interval_days = request.form.get(prefix + "repeat_interval_days", "").strip()
    if not start or not count or not interval_days:
        return []

    try:
        count_value = min(int(count), 24)
        interval_value = max(int(interval_days), 1)
        start_date = datetime.fromisoformat(start)
    except ValueError:
        abort(400)

    return [
        (start_date + timedelta(days=interval_value * index)).strftime("%Y-%m-%dT%H:%M")
        for index in range(count_value)
    ]


def _datetime_from_form(prefix="", base_name="scheduled"):
    legacy_value = request.form.get(prefix + base_name + "_at", "").strip()
    date_value = request.form.get(prefix + base_name + "_date", "").strip()
    time_value = request.form.get(prefix + base_name + "_time", "").strip()

    if date_value:
        return _normalize_datetime_value(f"{date_value}T{time_value or '18:00'}")
    if legacy_value:
        return _normalize_datetime_value(legacy_value)
    return ""


def _normalize_datetime_value(value):
    value = value.strip()
    if not value:
        return ""
    if len(value) == 10:
        value = f"{value}T18:00"
    if " " in value and "T" not in value:
        value = value.replace(" ", "T", 1)
    normalized = value[:16]
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        abort(400)
    return parsed.strftime("%Y-%m-%dT%H:%M")


def _datetime_parts(value):
    normalized = _normalize_datetime_value(value or "")
    if not normalized:
        return {"date": "", "time": ""}
    if "T" not in normalized:
        return {"date": normalized[:10], "time": "18:00"}
    date_value, time_value = normalized.split("T", 1)
    return {"date": date_value, "time": (time_value or "18:00")[:5]}


def _safe_next_url():
    next_url = request.args.get("next", "")
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return ""
    return next_url if next_url.startswith("/") else ""


def _is_safe_feed_url(url):
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and len(url) <= 500
