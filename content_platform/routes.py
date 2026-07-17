from calendar import Calendar, month_name
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, session, url_for

from .models import (
    FORMAT_MEDIA_GUIDES,
    FORMAT_MEDIA_RULES,
    PLATFORM_CONTENT_FORMATS,
    PLATFORM_MEDIA_GUIDES,
    PLATFORMS,
    PLATFORM_CONTENT_LIMITS,
    SOURCE_TYPES,
    STATUSES,
    Post,
    content_limit_for_post,
    default_content_format,
    truncate_content_for_platform,
)
from .security import validate_csrf
from .auth import is_logged_in, login_required, verify_user_credentials
from .services.analytics import build_platform_counts, build_status_counts
from .services.clock import app_now
from .services.media import delete_media, get_media_for_post, get_media_for_posts, save_media_files
from .services.publisher import process_publication_queue, publish_post_now, publish_rss_group_now
from .services.reporting import send_daily_publication_report
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
    update_rss_group_library_fields,
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
    update_library_post_fields,
)
from .services.social_accounts import (
    SOCIAL_ACCOUNT_SCHEMAS,
    STATUS_CONNECTED,
    credential_metadata,
    credential_field_names,
    credential_summary,
    delete_social_account,
    decrypt_credentials_for_publisher,
    public_credential_values,
    save_social_account,
    social_accounts_by_platform,
    update_social_account_credentials,
)
from .services.squared_feeds import SQUARED_FEEDS


bp = Blueprint("main", __name__)
NEWS_REPEAT_COUNT = "3"
NEWS_REPEAT_INTERVAL_DAYS = "2"
META_GRAPH_TIMEOUT_SECONDS = 8
FACEBOOK_OAUTH_SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
]
FACEBOOK_REQUIRED_SCOPES = [
    "pages_read_engagement",
    "pages_manage_posts",
]
INSTAGRAM_REQUIRED_SCOPES = [
    "instagram_basic",
    "instagram_content_publish",
]


@bp.get("/privacy")
def privacy_policy():
    return render_template("privacy.html")


@bp.get("/terms")
def terms_of_service():
    return render_template("terms.html")


@bp.route("/meta/deauthorize", methods=["GET", "POST"])
def meta_deauthorize():
    return jsonify({"ok": True, "message": "App deauthorization received."})


@bp.route("/meta/data-deletion", methods=["GET", "POST"])
def meta_data_deletion():
    confirmation_code = secrets.token_urlsafe(12)
    return jsonify(
        {
            "url": _external_oauth_url("main.data_deletion_status", code=confirmation_code),
            "confirmation_code": confirmation_code,
        }
    )


@bp.get("/meta/data-deletion/status/<code>")
def data_deletion_status(code):
    return render_template("data_deletion_status.html", confirmation_code=code)


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


@bp.post("/internal/reports/daily")
def trigger_daily_report():
    expected_token = os.environ.get("DAILY_REPORT_RUN_TOKEN", "")
    supplied_token = _bearer_token()
    if not expected_token or not supplied_token or not hmac.compare_digest(supplied_token, expected_token):
        abort(404)

    send_daily_publication_report()
    return jsonify({"ok": True, "message": "Daily publication report sent."})


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
        social_token_metadata={
            platform: credential_metadata(account) for platform, account in social_accounts.items()
        },
        social_account_schemas=SOCIAL_ACCOUNT_SCHEMAS,
        oauth_callback_urls={
            "meta": _external_oauth_url("main.meta_oauth_callback"),
            "threads": _external_oauth_url("main.threads_oauth_callback"),
        },
        platforms=PLATFORMS,
    )


@bp.route("/posts")
def posts():
    refresh_rss_content_types()
    source_types = SOURCE_TYPES
    media_kinds = {
        "story": "Stories",
        "video": "Videos",
        "image": "Images",
        "text": "Text",
    }
    sort_options = _post_sort_options()
    filters = {
        "status": request.args.get("status", ""),
        "platform": request.args.get("platform", ""),
        "source_type": request.args.get("source_type", ""),
        "media_kind": request.args.get("media_kind", ""),
        "search": request.args.get("search", ""),
        "sort": request.args.get("sort", "scheduled_asc"),
    }
    if filters["status"] and filters["status"] not in STATUSES:
        filters["status"] = ""
    if filters["platform"] and filters["platform"] not in PLATFORMS:
        filters["platform"] = ""
    if filters["source_type"] and filters["source_type"] not in source_types:
        filters["source_type"] = ""
    if filters["media_kind"] and filters["media_kind"] not in media_kinds:
        filters["media_kind"] = ""
    if filters["sort"] not in sort_options:
        filters["sort"] = "scheduled_asc"
    filtered_posts = get_all_posts(filters)
    media_by_post = get_media_for_posts([post["id"] for post in filtered_posts])
    schedules_by_post = get_schedules_for_posts([post["id"] for post in filtered_posts])
    post_rows = _aggregate_posts_for_library(filtered_posts, media_by_post, schedules_by_post)
    post_rows = _decorate_post_rows_for_library(post_rows, media_by_post, schedules_by_post)
    if filters["media_kind"]:
        post_rows = [row for row in post_rows if row["library_kind"] == filters["media_kind"]]
    post_rows = _sort_post_rows(post_rows, filters["sort"])
    return render_template(
        "posts.html",
        posts=post_rows,
        media_by_post=media_by_post,
        schedules_by_post=schedules_by_post,
        statuses=STATUSES,
        platforms=PLATFORMS,
        source_types=source_types,
        media_kinds=media_kinds,
        content_formats=PLATFORM_CONTENT_FORMATS,
        sort_options=sort_options,
        filters=filters,
    )


@bp.post("/posts/library-update")
def update_posts_library():
    validate_csrf()
    source_types = set(SOURCE_TYPES)
    action = request.form.get("action", "")

    selected_ids = request.form.getlist("selected_post_ids")
    post_ids = [item for item in selected_ids if item.isdigit()]
    rss_item_ids = [
        item.removeprefix("rss:")
        for item in selected_ids
        if item.startswith("rss:") and item.removeprefix("rss:").isdigit()
    ]

    if action == "bulk_delete":
        if not selected_ids:
            flash("Select at least one post first.", "warning")
            return redirect(_posts_redirect_args())

        deleted = 0
        for post_id in post_ids:
            delete_post(post_id)
            deleted += 1
        for rss_item_id in rss_item_ids:
            delete_rss_group(rss_item_id)
            deleted += 1

        flash(f"Deleted {deleted} selected item(s).", "success" if deleted else "warning")
        return redirect(_posts_redirect_args())

    if action == "bulk_update":
        platform = request.form.get("platform", "")
        source_type = request.form.get("source_type", "")
        content_format = request.form.get("content_format", "")

        if platform and platform not in PLATFORMS:
            abort(400)
        if source_type and source_type not in source_types:
            abort(400)
        target_platform = platform or ""
        if content_format:
            valid_formats = PLATFORM_CONTENT_FORMATS.get(target_platform, []) if target_platform else {
                content_format
                for formats in PLATFORM_CONTENT_FORMATS.values()
                for content_format in formats
            }
            if content_format not in valid_formats:
                abort(400)
        if not selected_ids:
            flash("Select at least one post first.", "warning")
            return redirect(_posts_redirect_args())
        if not platform and not source_type and not content_format:
            flash("Choose at least one bulk change.", "warning")
            return redirect(_posts_redirect_args())

        updated = update_library_post_fields(
            post_ids,
            platform=platform,
            source_type=source_type,
            content_format=content_format,
        )
        updated += update_rss_group_library_fields(
            rss_item_ids,
            source_type=source_type,
            content_format=content_format,
        )
        message = f"Updated {updated} item(s)."
        if platform and rss_item_ids:
            message += " Mix groups kept their existing platforms."
        flash(message if updated else "No items were updated.", "success" if updated else "warning")
        return redirect(_posts_redirect_args())

    abort(400)


def _posts_redirect_args():
    allowed = {"search", "platform", "status", "source_type", "media_kind", "sort"}
    args = {}
    for key in allowed:
        value = request.form.get(f"return_{key}", "")
        if value:
            args[key] = value
    return url_for("main.posts", **args)


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


def _decorate_post_rows_for_library(rows, media_by_post, schedules_by_post):
    for row in rows:
        kind, label = _library_media_kind(row, media_by_post)
        row["library_kind"] = kind
        row["library_kind_label"] = label
        schedule_label, schedule_extra = _library_schedule_summary(row, schedules_by_post)
        row["schedule_label"] = schedule_label
        row["schedule_extra"] = schedule_extra
        row["created_at_label"] = _format_datetime_display(row.get("created_at", ""))
    return rows


def _library_media_kind(row, media_by_post):
    if row.get("is_rss_group"):
        return "mixed", "Mix"

    content_format = row.get("content_format", "")
    media_items = media_by_post.get(row["id"], [])
    media_types = {item["media_type"] for item in media_items}

    if "Story" in content_format:
        return "story", "Story"
    if content_format in {"Reel", "Short"} or "Video" in content_format or "video" in media_types:
        return "video", "Video"
    if content_format in {"Image Post", "Carousel"} or "image" in media_types:
        return "image", "Image"
    return "text", "Text"


def _library_schedule_summary(row, schedules_by_post):
    if row.get("is_rss_group"):
        if row.get("scheduled_at"):
            extra = max(0, int(row.get("schedule_total") or 0) - 1)
            return _format_datetime_display(row["scheduled_at"]), extra
        return "Not scheduled", 0

    values = []
    if row.get("scheduled_at"):
        values.append(row["scheduled_at"])
    values.extend(
        schedule["scheduled_at"]
        for schedule in schedules_by_post.get(row["id"], [])
        if schedule["scheduled_at"]
    )
    unique_values = sorted(set(values))
    if not unique_values:
        return "Not scheduled", 0
    return _format_datetime_display(unique_values[0]), max(0, len(unique_values) - 1)


def _format_datetime_display(value):
    if not value:
        return ""
    normalized = str(value).strip().replace(" ", "T", 1)
    if "." in normalized:
        normalized = normalized.split(".", 1)[0]
    if normalized.endswith("+00"):
        normalized = normalized[:-3]
    if "+" in normalized:
        normalized = normalized.split("+", 1)[0]
    try:
        parsed = datetime.fromisoformat(normalized[:16])
    except ValueError:
        return str(value)
    return parsed.strftime("%d/%m/%Y %H:%M")


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
    today = app_now()
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
        if content_type not in SOURCE_TYPES:
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
        general_schedule_dates = _schedule_dates_from_general_form(content_type)
        general_values["scheduled_at"], general_values["status"] = _scheduled_values(
            general_values["status"],
            general_values["scheduled_at"],
            general_schedule_dates,
            current_status=posts[0]["status"] if posts else "",
        )
        general_media_files = request.files.getlist("general_media_files")
        updates = []
        schedule_dates_by_post = {}
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
            schedule_dates = (
                _schedule_dates_from_prefixed_form(prefix, content_type)
                if _uses_field_override(prefix, "schedule")
                else general_schedule_dates
            )
            schedule_dates_by_post[post["id"]] = schedule_dates
            scheduled_at = _datetime_from_form(prefix) if _uses_field_override(prefix, "schedule") else general_values["scheduled_at"]
            scheduled_at, status = _scheduled_values(status, scheduled_at, schedule_dates, current_status=post["status"])
            updates.append(
                {
                    "post_id": post["id"],
                    "title": title,
                    "content": content,
                    "hashtags": hashtags,
                    "content_format": content_format,
                    "status": status,
                    "scheduled_at": scheduled_at,
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
            replace_schedules(post["id"], schedule_dates_by_post.get(post["id"], []))
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
        post_data = _post_from_form()
        schedule_dates = _schedule_dates_from_form(post_data.source_type)
        _apply_schedule_status(post_data, schedule_dates)
        post_id = create_post(post_data)
        replace_schedules(post_id, schedule_dates)
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
        post_data = _post_from_form()
        schedule_dates = _schedule_dates_from_form(post_data.source_type)
        _apply_schedule_status(post_data, schedule_dates, current_status=post["status"])
        update_post(post_id, post_data)
        replace_schedules(post_id, schedule_dates)
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
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify({"ok": True, "media_id": media_id})
    if post_id:
        return redirect(url_for("main.edit_post", post_id=post_id))
    return redirect(url_for("main.posts"))


@bp.post("/posts/<int:post_id>/delete")
def remove_post(post_id):
    validate_csrf()
    delete_post(post_id)
    return redirect(_posts_redirect_args())


@bp.post("/posts/<int:post_id>/publish-now")
def publish_single_post_now(post_id):
    validate_csrf()
    result = publish_post_now(post_id)
    if result["ok"]:
        flash("Post published successfully.", "success")
    else:
        flash(f"Publication failed: {result['message']}", "warning")
    return redirect(_posts_redirect_args())


@bp.post("/rss/articles/<int:rss_item_id>/delete")
def remove_rss_article(rss_item_id):
    validate_csrf()
    delete_rss_group(rss_item_id)
    flash("RSS article and its network versions deleted.", "success")
    return redirect(_posts_redirect_args())


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
    return redirect(_posts_redirect_args())


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


@bp.post("/settings/social-accounts/Facebook/connect")
@login_required
def connect_facebook_account():
    validate_csrf()
    account = decrypt_credentials_for_publisher("Facebook")
    credentials = (account or {}).get("credentials", {})
    page_id = credentials.get("page_id", "")
    app_id = credentials.get("app_id", "")
    app_secret = credentials.get("app_secret", "")
    if not page_id or not app_id or not app_secret:
        flash("Save Facebook Page ID, App ID, and App Secret before connecting Facebook.", "warning")
        return redirect(url_for("main.social_account_settings"))

    state = secrets.token_urlsafe(24)
    session["meta_oauth_state"] = state
    session["meta_oauth_platform"] = "Facebook"
    redirect_uri = _external_oauth_url("main.meta_oauth_callback")
    authorization_url = "https://www.facebook.com/v20.0/dialog/oauth?" + urlencode(
        {
            "client_id": app_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(FACEBOOK_OAUTH_SCOPES),
            "response_type": "code",
            "state": state,
        }
    )
    return redirect(authorization_url)


@bp.get("/settings/social-accounts/meta/callback")
@login_required
def meta_oauth_callback():
    if request.args.get("state") != session.pop("meta_oauth_state", ""):
        flash("Meta authorization state did not match. Please try connecting again.", "warning")
        return redirect(url_for("main.social_account_settings"))

    platform = session.pop("meta_oauth_platform", "")
    code = request.args.get("code", "").strip()
    if not code:
        flash(request.args.get("error_description") or "Meta did not return an authorization code.", "warning")
        return redirect(url_for("main.social_account_settings"))

    redirect_uri = _external_oauth_url("main.meta_oauth_callback")
    if platform == "Facebook":
        return _complete_facebook_oauth_connection(code, redirect_uri)

    flash("Meta authorization did not identify a supported platform. Please try again.", "warning")
    return redirect(url_for("main.social_account_settings"))


@bp.get("/settings/social-accounts/Facebook/callback")
@login_required
def facebook_oauth_callback():
    if request.args.get("state") != session.pop("facebook_oauth_state", ""):
        flash("Facebook authorization state did not match. Please try connecting again.", "warning")
        return redirect(url_for("main.social_account_settings"))

    code = request.args.get("code", "").strip()
    if not code:
        flash(request.args.get("error_description") or "Facebook did not return an authorization code.", "warning")
        return redirect(url_for("main.social_account_settings"))

    redirect_uri = _external_oauth_url("main.facebook_oauth_callback")
    return _complete_facebook_oauth_connection(code, redirect_uri)


def _complete_facebook_oauth_connection(code, redirect_uri):
    account = decrypt_credentials_for_publisher("Facebook")
    credentials = (account or {}).get("credentials", {})
    page_id = credentials.get("page_id", "")
    app_id = credentials.get("app_id", "")
    app_secret = credentials.get("app_secret", "")
    if not page_id or not app_id or not app_secret:
        flash("Facebook Page ID, App ID, or App Secret are missing. Save them and connect again.", "warning")
        return redirect(url_for("main.social_account_settings"))

    try:
        token_payload = _exchange_facebook_authorization_code(app_id, app_secret, code, redirect_uri)
        result = _generate_long_lived_facebook_page_token(
            page_id=page_id,
            app_id=app_id,
            app_secret=app_secret,
            short_lived_user_token=token_payload["access_token"],
        )
    except (KeyError, RuntimeError) as exc:
        add_log(None, "ERROR", f"Facebook OAuth connection failed: {exc}")
        flash(f"Facebook connection failed: {exc}", "warning")
    else:
        update_social_account_credentials(
            "Facebook",
            {
                "access_token": result["page_access_token"],
                "token_expires_at": result["token_expires_at"],
                "token_expires_label": result["token_expires_label"],
                "token_source": "OAuth long-lived Page token",
            },
            connection_status=STATUS_CONNECTED,
        )
        add_log(None, "SUCCESS", f"Facebook OAuth connected and Page token saved for Page ID {page_id}.")
        flash(f"Facebook connected. Page token saved automatically. {result['token_expires_label']}", "success")
    return redirect(url_for("main.social_account_settings"))


@bp.post("/settings/social-accounts/Facebook/extend-token")
@login_required
def extend_facebook_page_token():
    validate_csrf()
    account = decrypt_credentials_for_publisher("Facebook")
    credentials = (account or {}).get("credentials", {})
    page_id = credentials.get("page_id", "")
    app_id = credentials.get("app_id", "")
    app_secret = credentials.get("app_secret", "")
    short_lived_user_token = request.form.get("short_lived_user_token", "").strip()

    if not page_id or not app_id or not app_secret:
        flash("Save Facebook Page ID, App ID, and App Secret before generating a long-lived Page token.", "warning")
        return redirect(url_for("main.social_account_settings"))
    if not short_lived_user_token:
        flash("Paste a short-lived user token from Graph API Explorer first.", "warning")
        return redirect(url_for("main.social_account_settings"))

    try:
        result = _generate_long_lived_facebook_page_token(
            page_id=page_id,
            app_id=app_id,
            app_secret=app_secret,
            short_lived_user_token=short_lived_user_token,
        )
    except RuntimeError as exc:
        add_log(None, "ERROR", f"Facebook long-lived token generation failed: {exc}")
        flash(f"Facebook token generation failed: {exc}", "warning")
    else:
        update_social_account_credentials(
            "Facebook",
            {
                "access_token": result["page_access_token"],
                "token_expires_at": result["token_expires_at"],
                "token_expires_label": result["token_expires_label"],
                "token_source": "Long-lived Page token",
            },
            connection_status=STATUS_CONNECTED,
        )
        add_log(None, "SUCCESS", f"Facebook long-lived Page token saved for Page ID {page_id}.")
        flash(f"Facebook long-lived Page token saved. {result['token_expires_label']}", "success")
    return redirect(url_for("main.social_account_settings"))


@bp.post("/settings/social-accounts/Threads/connect")
@bp.post("/settings/social-accounts/threads/connect")
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
    redirect_uri = _external_oauth_url("main.threads_oauth_callback")
    authorization_url = "https://www.threads.com/oauth/authorize?" + urlencode(
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
@bp.get("/settings/social-accounts/threads/callback")
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

    redirect_uri = _external_oauth_url("main.threads_oauth_callback")
    try:
        token_payload = _exchange_threads_authorization_code(app_id, app_secret, code, redirect_uri)
        access_token = token_payload.get("access_token")
        if access_token:
            token_payload.update(_exchange_threads_long_lived_token(app_secret, access_token))
    except RuntimeError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("main.social_account_settings"))

    access_token = token_payload.get("access_token")
    user_id = str(token_payload.get("user_id") or "")
    if not access_token or not user_id:
        flash("Threads authorization did not return both access_token and user_id.", "warning")
        return redirect(url_for("main.social_account_settings"))

    update_social_account_credentials(
        "Threads",
        {
            "threads_user_id": user_id,
            "access_token": access_token,
            "token_expires_at": _token_expires_at_from_seconds(token_payload.get("expires_in")),
            "token_expires_label": _format_relative_expiry(token_payload.get("expires_in")),
            "token_source": "Threads OAuth long-lived token",
        },
        connection_status=STATUS_CONNECTED,
    )
    add_log(None, "INFO", "Threads OAuth connected and credentials updated.")
    flash("Threads connected. Long-lived user token saved.", "success")
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


def _exchange_threads_long_lived_token(app_secret, short_lived_access_token):
    return _threads_get_json(
        "https://graph.threads.net/access_token",
        {
            "grant_type": "th_exchange_token",
            "client_secret": app_secret,
            "access_token": short_lived_access_token,
        },
        "Threads long-lived token exchange",
    )


def _exchange_facebook_authorization_code(app_id, app_secret, code, redirect_uri):
    return _meta_get_json(
        "https://graph.facebook.com/v20.0/oauth/access_token",
        {
            "client_id": app_id,
            "client_secret": app_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        "Facebook OAuth code exchange",
    )


def _verify_social_account(account):
    platform = account["platform"]
    credentials = account["credentials"]
    if platform == "Facebook":
        return _verify_facebook_account(credentials)
    if platform == "Instagram":
        return _verify_instagram_account(credentials)
    if platform == "Threads":
        return _verify_threads_account(credentials)
    raise RuntimeError("Credential verification is currently available for Facebook, Instagram, and Threads.")


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
    missing_scopes = [scope for scope in FACEBOOK_REQUIRED_SCOPES if scope not in scopes]
    if scopes and missing_scopes:
        raise RuntimeError(f"Token is readable, but missing scopes: {', '.join(missing_scopes)}.")
    details.append("publish scopes are present")
    return "; ".join(details) + "."


def _verify_instagram_account(credentials):
    instagram_id = credentials.get("instagram_business_id", "")
    facebook_page_id = credentials.get("facebook_page_id", "")
    facebook_account = decrypt_credentials_for_publisher("Facebook")
    facebook_credentials = (facebook_account or {}).get("credentials", {})
    page_id = facebook_page_id or facebook_credentials.get("page_id", "")
    access_token = facebook_credentials.get("access_token", "")
    if not instagram_id:
        raise RuntimeError("Instagram needs the Instagram Business/Creator ID.")
    if not page_id:
        raise RuntimeError("Instagram needs the linked Facebook Page ID.")
    if not access_token:
        raise RuntimeError("Instagram uses the Facebook Page token. Connect Facebook first, then verify Instagram.")

    scopes = _meta_token_scopes(facebook_credentials)
    missing_scopes = [scope for scope in INSTAGRAM_REQUIRED_SCOPES if scope not in scopes]
    if missing_scopes:
        raise RuntimeError(
            "The saved Facebook Page token can publish to Facebook, but is missing Instagram permissions: "
            f"{', '.join(missing_scopes)}. Use Connect Facebook again and accept Instagram access."
        )

    page = _meta_get_json(
        f"https://graph.facebook.com/v20.0/{page_id}",
        {"fields": "id,name,instagram_business_account{id,username}", "access_token": access_token},
        "Instagram linked Page lookup",
    )
    linked_instagram = page.get("instagram_business_account") or {}
    if not linked_instagram:
        raise RuntimeError(
            f"Facebook Page {page.get('name') or page.get('id')} is readable, but Meta did not return a linked Instagram professional account. "
            "Confirm the Instagram account is connected to this Facebook Page in Meta Business Suite, then use Connect Facebook again."
        )
    if linked_instagram and str(linked_instagram.get("id", "")) != str(instagram_id):
        raise RuntimeError(
            "The saved Facebook Page token is linked to Instagram ID "
            f"{linked_instagram.get('id')}, but the Instagram card has {instagram_id}."
        )
    account = _meta_get_json(
        f"https://graph.facebook.com/v20.0/{instagram_id}",
        {"fields": "id,username", "access_token": access_token},
        "Instagram account lookup",
    )
    return (
        f"Instagram account {account.get('username') or account.get('id')} is readable "
        f"through Facebook Page {page.get('name') or page.get('id')}."
    )


def _verify_threads_account(credentials):
    threads_user_id = credentials.get("threads_user_id", "")
    access_token = credentials.get("access_token", "")
    if not threads_user_id or not access_token:
        raise RuntimeError("Threads needs Threads User ID and User Access Token.")
    _guard_threads_token_shape(access_token)

    account = _threads_get_json(
        "https://graph.threads.net/v1.0/me",
        {"fields": "id,username", "access_token": access_token},
        "Threads account lookup",
    )
    if str(account.get("id", "")) != str(threads_user_id):
        raise RuntimeError(
            "The Threads token is readable, but it belongs to Threads ID "
            f"{account.get('id')}, not the configured ID {threads_user_id}."
        )
    return f"Threads account {account.get('username') or account.get('id')} is readable."


def _guard_threads_token_shape(access_token):
    if access_token.strip().startswith("EAA"):
        raise RuntimeError(
            "The saved token looks like a Facebook/Meta Graph token, not a Threads token. "
            "Remove the Threads credentials, save the Threads App ID/App Secret again, then use Connect Threads."
        )


def _threads_get_json(url, params, endpoint_name):
    request_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(Request(request_url, method="GET"), timeout=META_GRAPH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{endpoint_name} error {exc.code}: {_clean_threads_error(detail)}") from exc
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{endpoint_name} failed or timed out while contacting Threads: {exc}") from exc


def _clean_threads_error(detail):
    cleaned = _clean_meta_error(detail)
    if "Cannot parse access token" in cleaned:
        return (
            "Invalid OAuth access token - Cannot parse access token. "
            "This usually means the saved token is not a Threads OAuth token. "
            "Use Connect Threads to generate a Threads token; do not paste a Facebook/Graph Explorer EAA token."
        )
    return cleaned


def _external_oauth_url(endpoint, **values):
    # Render terminates HTTPS before Flask sees the request. For OAuth and Meta
    # callbacks, prefer the configured production base URL when available.
    app_base_url = os.environ.get("APP_BASE_URL", "").rstrip("/")
    if app_base_url:
        return app_base_url + url_for(endpoint, **values)
    if request.host.endswith("onrender.com"):
        return url_for(endpoint, _external=True, _scheme="https", **values)
    return url_for(endpoint, _external=True, **values)


def _generate_long_lived_facebook_page_token(page_id, app_id, app_secret, short_lived_user_token):
    return _generate_long_lived_meta_page_token(
        page_id=page_id,
        app_id=app_id,
        app_secret=app_secret,
        short_lived_user_token=short_lived_user_token,
        required_scopes=FACEBOOK_REQUIRED_SCOPES + INSTAGRAM_REQUIRED_SCOPES,
        lookup_label="Facebook",
    )


def _generate_long_lived_meta_page_token(page_id, app_id, app_secret, short_lived_user_token, required_scopes, lookup_label):
    exchange = _meta_get_json(
        "https://graph.facebook.com/v20.0/oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": app_id,
            "client_secret": app_secret,
            "fb_exchange_token": short_lived_user_token,
        },
        "Facebook long-lived user token exchange",
    )
    long_lived_user_token = exchange.get("access_token")
    if not long_lived_user_token:
        raise RuntimeError("Meta did not return a long-lived user token.")

    pages = _meta_get_json(
        "https://graph.facebook.com/v20.0/me/accounts",
        {"fields": "id,name,access_token,tasks", "access_token": long_lived_user_token},
        f"{lookup_label} Page token lookup",
    )
    page = _find_meta_page(pages.get("data") or [], page_id)
    if not page:
        raise RuntimeError(
            "The long-lived user token did not return the configured Facebook Page. "
            "Generate the user token with pages_show_list and the required publishing permissions."
        )
    page_access_token = page.get("access_token")
    if not page_access_token:
        raise RuntimeError("Meta returned the Page but did not include a Page access token.")

    token_debug = _debug_meta_token(page_access_token, app_id, app_secret)
    scopes = _meta_scopes_from_debug_data(token_debug)
    missing_scopes = [scope for scope in required_scopes if scope not in scopes]
    if missing_scopes:
        raise RuntimeError(f"Generated Page token is missing scopes: {', '.join(missing_scopes)}.")
    expires_at = int(token_debug.get("expires_at") or 0)
    return {
        "page_access_token": page_access_token,
        "token_expires_at": str(expires_at) if expires_at else "",
        "token_expires_label": _format_meta_expiry(expires_at),
    }


def _find_meta_page(pages, page_id):
    for page in pages:
        if str(page.get("id", "")) == str(page_id):
            return page
    return None


def _meta_token_scopes(credentials):
    app_id = credentials.get("app_id", "")
    app_secret = credentials.get("app_secret", "")
    access_token = credentials.get("access_token", "")
    if not app_id or not app_secret or not access_token:
        return []
    data = _debug_meta_token(access_token, app_id, app_secret)
    return _meta_scopes_from_debug_data(data)


def _debug_meta_token(access_token, app_id, app_secret):
    payload = _meta_get_json(
        "https://graph.facebook.com/debug_token",
        {"input_token": access_token, "access_token": f"{app_id}|{app_secret}"},
        "Meta token debug",
    )
    data = payload.get("data") or {}
    if data.get("is_valid") is False:
        raise RuntimeError("Meta says this access token is not valid.")
    return data


def _meta_scopes_from_debug_data(data):
    scopes = set(data.get("scopes") or [])
    for granular_scope in data.get("granular_scopes") or []:
        scope = granular_scope.get("scope")
        if scope:
            scopes.add(scope)
    return scopes


def _format_meta_expiry(expires_at):
    if not expires_at:
        return "Meta reports no fixed expiry for this Page token."
    expires = datetime.fromtimestamp(expires_at, tz=timezone.utc)
    return f"Expires at {expires.strftime('%Y-%m-%d %H:%M UTC')}."


def _token_expires_at_from_seconds(expires_in):
    try:
        seconds = int(expires_in or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    return str(int(datetime.now(tz=timezone.utc).timestamp()) + seconds)


def _format_relative_expiry(expires_in):
    try:
        seconds = int(expires_in or 0)
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return ""
    expires_at = int(datetime.now(tz=timezone.utc).timestamp()) + seconds
    return _format_meta_expiry(expires_at)


def _meta_get_json(url, params, endpoint_name):
    request_url = f"{url}?{urlencode(params)}"
    try:
        with urlopen(Request(request_url, method="GET"), timeout=META_GRAPH_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{endpoint_name} error {exc.code}: {_clean_meta_error(detail)}") from exc
    except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{endpoint_name} failed or timed out while contacting Meta: {exc}") from exc


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
        role = verify_user_credentials(request.form.get("username", ""), request.form.get("password", ""))
        if role:
            from flask import session

            session["admin_authenticated"] = True
            session["user_role"] = role
            return redirect(_safe_next_url() or url_for("main.dashboard"))
        flash("Invalid username or password.", "warning")

    return render_template("login.html")


@bp.post("/logout")
def logout():
    validate_csrf()
    from flask import session

    session.pop("admin_authenticated", None)
    session.pop("user_role", None)
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
            request.form.get("copy_template", "").strip(),
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
            request.form.get("copy_template", "").strip(),
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


def _scheduled_values(status, scheduled_at, schedule_dates, current_status=""):
    schedule_dates = schedule_dates or []
    if not scheduled_at and schedule_dates:
        scheduled_at = schedule_dates[0]
    if scheduled_at or schedule_dates:
        status = "Scheduled"
    elif status == "Published" and current_status != "Published":
        status = "Draft"
    return scheduled_at, status


def _apply_schedule_status(post, schedule_dates, current_status=""):
    post.scheduled_at, post.status = _scheduled_values(
        post.status,
        post.scheduled_at,
        schedule_dates,
        current_status=current_status,
    )


def _post_from_form():
    title = request.form["title"].strip()
    content = request.form["content"].strip()
    hashtags = request.form.get("hashtags", "").strip()
    platform = request.form["platform"]
    status = request.form["status"]
    source_type = request.form.get("source_type", "Regular")
    content_format = request.form.get("content_format", "").strip() or default_content_format(platform)
    scheduled_at = _datetime_from_form()

    if platform not in PLATFORMS:
        abort(400)
    if status not in STATUSES:
        abort(400)
    if source_type not in SOURCE_TYPES:
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
    if (
        status == "Scheduled"
        and not scheduled_at
        and not request.form.get("schedule_dates", "").strip()
        and not request.form.get("repeat_date", "").strip()
        and not request.form.get("repeat_count", "").strip()
    ):
        abort(400)

    return Post(
        title=title,
        content=content,
        hashtags=hashtags,
        platform=platform,
        content_format=content_format,
        scheduled_at=scheduled_at,
        status=status,
        source_type=source_type,
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


def _schedule_dates_from_form(source_type="Regular"):
    dates = []
    primary = _datetime_from_form()
    if primary:
        dates.append(primary)
    extra_dates = request.form.get("schedule_dates", "")
    dates.extend(_normalize_datetime_value(line.strip()) for line in extra_dates.splitlines() if line.strip())
    dates.extend(_recurring_dates_from_form("", source_type, primary))
    return _unique_schedule_dates(dates)


def _schedule_dates_from_prefixed_form(prefix, source_type="Regular"):
    dates = []
    primary = _datetime_from_form(prefix)
    if primary:
        dates.append(primary)

    extra_dates = request.form.get(prefix + "schedule_dates", "")
    dates.extend(_normalize_datetime_value(line.strip()) for line in extra_dates.splitlines() if line.strip())
    dates.extend(_recurring_dates_from_form(prefix, source_type, primary))
    return _unique_schedule_dates(dates)


def _schedule_dates_from_general_form(source_type="Regular"):
    dates = []
    primary = _datetime_from_form("", "general_scheduled")
    if primary:
        dates.append(primary)

    extra_dates = request.form.get("general_schedule_dates", "")
    dates.extend(_normalize_datetime_value(line.strip()) for line in extra_dates.splitlines() if line.strip())
    dates.extend(_recurring_dates_from_form("general_", source_type, primary))
    return _unique_schedule_dates(dates)


def _unique_schedule_dates(dates):
    seen = set()
    cleaned = []
    for date in dates:
        if not date or date in seen:
            continue
        seen.add(date)
        cleaned.append(date)
    return cleaned


def _recurring_dates_from_form(prefix, source_type="Regular", fallback_start=""):
    start = _datetime_from_form(prefix, "repeat") or fallback_start
    count = request.form.get(prefix + "repeat_count", "").strip()
    interval_days = request.form.get(prefix + "repeat_interval_days", "").strip()
    if source_type == "News" and start:
        count = count or NEWS_REPEAT_COUNT
        interval_days = interval_days or NEWS_REPEAT_INTERVAL_DAYS
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


def _bearer_token():
    authorization = request.headers.get("Authorization", "")
    prefix = "Bearer "
    if not authorization.startswith(prefix):
        return ""
    return authorization[len(prefix) :].strip()
