from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from .models import (
    FORMAT_MEDIA_GUIDES,
    PLATFORM_CONTENT_FORMATS,
    PLATFORM_MEDIA_GUIDES,
    PLATFORMS,
    STATUSES,
    Post,
    default_content_format,
)
from .security import validate_csrf
from .auth import is_logged_in, login_required, verify_admin_credentials
from .services.analytics import build_platform_counts, build_status_counts
from .services.media import delete_media, get_media_for_post, get_media_for_posts, save_media_files
from .services.publisher import process_publication_queue
from .services.rss import check_all_feeds, create_feed, delete_feed, list_feeds
from .services.rss_groups import get_rss_group, list_rss_groups, sync_rss_group_platforms, update_rss_group_posts
from .services.schedules import get_schedules_for_post, get_schedules_for_posts, replace_schedules
from .services.scheduler import (
    create_post,
    delete_post,
    get_all_posts,
    get_logs,
    get_post,
    update_post,
)
from .services.squared_feeds import SQUARED_FEEDS


bp = Blueprint("main", __name__)


@bp.route("/")
def dashboard():
    posts = get_all_posts()
    media_by_post = get_media_for_posts([post["id"] for post in posts[:8]])
    schedules_by_post = get_schedules_for_posts([post["id"] for post in posts[:8]])
    return render_template(
        "dashboard.html",
        posts=posts[:8],
        media_by_post=media_by_post,
        schedules_by_post=schedules_by_post,
        status_counts=build_status_counts(posts),
        platform_counts=build_platform_counts(posts),
    )


@bp.route("/posts")
def posts():
    filters = {
        "status": request.args.get("status", ""),
        "platform": request.args.get("platform", ""),
        "search": request.args.get("search", ""),
    }
    filtered_posts = get_all_posts(filters)
    media_by_post = get_media_for_posts([post["id"] for post in filtered_posts])
    schedules_by_post = get_schedules_for_posts([post["id"] for post in filtered_posts])
    post_rows = _aggregate_posts_for_library(filtered_posts, media_by_post, schedules_by_post)
    return render_template(
        "posts.html",
        posts=post_rows,
        media_by_post=media_by_post,
        schedules_by_post=schedules_by_post,
        statuses=STATUSES,
        platforms=PLATFORMS,
        filters=filters,
    )


def _aggregate_posts_for_library(posts, media_by_post, schedules_by_post):
    rows = []
    rss_groups = {}

    for post in posts:
        post_data = dict(post)
        if not post_data.get("rss_item_id"):
            post_data["is_rss_group"] = False
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
                "hashtags": post_data["hashtags"],
                "is_rss_group": True,
                "platforms": [],
                "statuses": [],
                "media_total": 0,
                "schedule_total": 0,
            },
        )
        group["platforms"].append(post_data["platform"])
        group["statuses"].append(post_data["status"])
        group["media_total"] += len(media_by_post.get(post_data["id"], []))
        group["schedule_total"] += len(schedules_by_post.get(post_data["id"], []))
        if post_data["scheduled_at"] and (not group["scheduled_at"] or post_data["scheduled_at"] < group["scheduled_at"]):
            group["scheduled_at"] = post_data["scheduled_at"]

    for group in rss_groups.values():
        group["platform"] = ", ".join(sorted(set(group["platforms"])))
        unique_statuses = sorted(set(group["statuses"]))
        group["status"] = unique_statuses[0] if len(unique_statuses) == 1 else "Mixed"
        rows.append(group)

    return rows


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
        updates = []
        for post in posts:
            prefix = f"post_{post['id']}_"
            if prefix + "title" not in request.form:
                continue
            status = request.form.get(prefix + "status", post["status"])
            content_format = request.form.get(prefix + "content_format", post["content_format"])
            if status not in STATUSES:
                abort(400)
            if content_format not in PLATFORM_CONTENT_FORMATS.get(post["platform"], []):
                abort(400)
            updates.append(
                {
                    "post_id": post["id"],
                    "title": request.form.get(prefix + "title", "").strip()[:120],
                    "content": request.form.get(prefix + "content", "").strip()[:2200],
                    "hashtags": request.form.get(prefix + "hashtags", "").strip()[:400],
                    "content_format": content_format,
                    "status": status,
                    "scheduled_at": request.form.get(prefix + "scheduled_at", "").strip(),
                }
            )
            if not updates[-1]["title"] or not updates[-1]["content"]:
                abort(400)

        update_rss_group_posts(updates)
        for post in posts:
            prefix = f"post_{post['id']}_"
            if prefix + "title" not in request.form:
                continue
            replace_schedules(post["id"], _schedule_dates_from_prefixed_form(prefix))
        flash("Article versions updated.", "success")
        return redirect(url_for("main.edit_rss_article", rss_item_id=rss_item_id))

    schedules_by_post = get_schedules_for_posts([post["id"] for post in posts])
    return render_template(
        "rss_article_edit.html",
        item=item,
        posts=posts,
        schedules_by_post=schedules_by_post,
        content_formats=PLATFORM_CONTENT_FORMATS,
        statuses=STATUSES,
        platforms=PLATFORMS,
    )


@bp.route("/posts/new", methods=["GET", "POST"])
def new_post():
    if request.method == "POST":
        validate_csrf()
        post_id = create_post(_post_from_form())
        replace_schedules(post_id, _schedule_dates_from_form())
        saved, skipped = save_media_files(post_id, request.files.getlist("media_files"))
        _flash_media_result(saved, skipped)
        return redirect(url_for("main.posts"))

    return render_template(
        "post_form.html",
        post=None,
        media=[],
        schedules=[],
        content_formats=PLATFORM_CONTENT_FORMATS,
        format_guides=FORMAT_MEDIA_GUIDES,
        media_guides=PLATFORM_MEDIA_GUIDES,
        statuses=STATUSES,
        platforms=PLATFORMS,
        action="Create",
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
        saved, skipped = save_media_files(post_id, request.files.getlist("media_files"))
        _flash_media_result(saved, skipped)
        return redirect(url_for("main.posts"))

    return render_template(
        "post_form.html",
        post=post,
        media=get_media_for_post(post_id),
        schedules=get_schedules_for_post(post_id),
        content_formats=PLATFORM_CONTENT_FORMATS,
        format_guides=FORMAT_MEDIA_GUIDES,
        media_guides=PLATFORM_MEDIA_GUIDES,
        statuses=STATUSES,
        platforms=PLATFORMS,
        action="Update",
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


@bp.post("/queue/process")
def process_queue():
    validate_csrf()
    process_publication_queue()
    return redirect(url_for("main.dashboard"))


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
    scheduled_at = request.form.get("scheduled_at", "")

    if platform not in PLATFORMS:
        abort(400)
    if status not in STATUSES:
        abort(400)
    if content_format not in PLATFORM_CONTENT_FORMATS.get(platform, []):
        abort(400)
    if not title or len(title) > 120:
        abort(400)
    if not content or len(content) > 2200:
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


def _schedule_dates_from_form():
    dates = []
    primary = request.form.get("scheduled_at", "").strip()
    if primary:
        dates.append(primary)
    extra_dates = request.form.get("schedule_dates", "")
    dates.extend(line.strip() for line in extra_dates.splitlines())
    return dates


def _schedule_dates_from_prefixed_form(prefix):
    dates = []
    primary = request.form.get(prefix + "scheduled_at", "").strip()
    if primary:
        dates.append(primary)

    extra_dates = request.form.get(prefix + "schedule_dates", "")
    dates.extend(line.strip() for line in extra_dates.splitlines())
    dates.extend(_recurring_dates_from_form(prefix))
    return dates


def _recurring_dates_from_form(prefix):
    start = request.form.get(prefix + "repeat_start", "").strip()
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


def _safe_next_url():
    next_url = request.args.get("next", "")
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return ""
    return next_url if next_url.startswith("/") else ""


def _is_safe_feed_url(url):
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc) and len(url) <= 500
