from datetime import datetime, timedelta
from html import unescape
import hashlib
import os
import re
import unicodedata
import xml.etree.ElementTree as ET
from urllib.error import URLError
from urllib.request import Request, urlopen
from urllib.parse import unquote, urlparse

from ..database import get_connection, insert_and_get_id
from ..models import default_content_format, source_type_label
from .scheduler import add_log


USER_AGENT = "ContentAutomationPlatform/1.0"
FRESHNESS_WINDOW_HOURS = 2.5


def list_feeds():
    with get_connection() as conn:
        feeds = conn.execute("SELECT * FROM rss_feeds ORDER BY created_at DESC").fetchall()
    return [_feed_with_health(feed) for feed in feeds]


def get_feed(feed_id):
    with get_connection() as conn:
        feed = conn.execute("SELECT * FROM rss_feeds WHERE id = ?", (feed_id,)).fetchone()
    return _feed_with_health(feed) if feed else None


def create_feed(name, url, target_platforms, default_hashtags, copy_template=""):
    content_type = classify_content_type(url)
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM rss_feeds WHERE url = ?", (url,)).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO rss_feeds (name, url, target_platforms, default_hashtags, copy_template, content_type)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, url, ",".join(target_platforms), default_hashtags, copy_template, content_type),
        )

    return True


def update_feed(feed_id, name, url, target_platforms, default_hashtags, copy_template=""):
    content_type = classify_content_type(url)
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM rss_feeds WHERE url = ? AND id != ?",
            (url, feed_id),
        ).fetchone()
        if existing:
            return False
        conn.execute(
            """
            UPDATE rss_feeds
            SET name = ?, url = ?, target_platforms = ?, default_hashtags = ?, copy_template = ?, content_type = ?
            WHERE id = ?
            """,
            (name, url, ",".join(target_platforms), default_hashtags, copy_template, content_type, feed_id),
        )
    return True


def delete_feed(feed_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))


def check_all_feeds(max_entries_per_feed=None):
    created = 0
    skipped = 0
    errors = []
    for feed in list_feeds():
        if not feed["is_active"]:
            continue
        try:
            result = check_feed(feed, max_entries_per_feed=max_entries_per_feed)
        except Exception as exc:
            message = f"{feed['name']}: {exc}"
            try:
                add_log(None, "ERROR", f"RSS check failed: {message}")
            except Exception:
                pass
            errors.append(message)
            _record_feed_check(feed["id"], 0, 0, [message])
            continue
        created += result["created"]
        skipped += result["skipped"]
        errors.extend(result["errors"])
    return {"created": created, "skipped": skipped, "errors": errors}


def check_feed(feed, max_entries_per_feed=None):
    created = 0
    skipped = 0
    errors = []

    try:
        entries = fetch_feed_entries(feed["url"])
    except (URLError, ET.ParseError, TimeoutError, ValueError) as exc:
        errors.append(f"{feed['name']}: {exc}")
        _record_feed_check(feed["id"], created, skipped, errors)
        return {"created": created, "skipped": skipped, "errors": errors}

    platforms = [item.strip() for item in feed["target_platforms"].split(",") if item.strip()]
    max_entries = max_entries_per_feed or int(os.environ.get("RSS_MAX_ENTRIES_PER_FEED", "10"))
    with get_connection() as conn:
        for entry in entries[:max_entries]:
            guid = entry["guid"]
            if _item_exists(conn, feed["id"], guid) or _url_exists(conn, entry["link"]):
                skipped += 1
                continue

            content_type = classify_content_type(entry["link"], fallback=feed["content_type"])
            rss_item_id = _remember_item(
                conn,
                feed["id"],
                guid,
                entry["title"],
                entry["link"],
                entry.get("image_url", ""),
                content_type,
                None,
            )
            first_post_id = None
            for platform in platforms:
                post_id = _create_rss_draft(conn, feed, entry, platform, rss_item_id, content_type)
                if first_post_id is None:
                    first_post_id = post_id
                conn.execute(
                    "INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)",
                    (post_id, "INFO", f"Draft created from RSS feed {feed['name']}."),
                )
                created += 1

            conn.execute("UPDATE rss_items SET post_id = ? WHERE id = ?", (first_post_id, rss_item_id))

        conn.execute(
            """
            UPDATE rss_feeds
            SET last_checked_at = ?,
                last_check_status = ?,
                last_check_message = ?,
                last_created_count = ?,
                last_skipped_count = ?,
                last_error_count = ?
            WHERE id = ?
            """,
            (
                _now_string(),
                _status_for_errors(errors),
                _message_for_result(created, skipped, errors),
                created,
                skipped,
                len(errors),
                feed["id"],
            ),
        )
    return {"created": created, "skipped": skipped, "errors": errors}


def fetch_feed_entries(url):
    request = Request(url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=15) as response:
        data = response.read(2_000_000)

    root = ET.fromstring(data)
    entries = _parse_rss(root)
    if not entries:
        entries = _parse_atom(root)
    return entries


def item_exists(feed_id, guid):
    with get_connection() as conn:
        return _item_exists(conn, feed_id, guid)


def remember_item(feed_id, guid, title, url, image_url, content_type, post_id):
    with get_connection() as conn:
        return _remember_item(conn, feed_id, guid, title, url, image_url, content_type, post_id)


def update_item_post(rss_item_id, post_id):
    with get_connection() as conn:
        conn.execute("UPDATE rss_items SET post_id = ? WHERE id = ?", (post_id, rss_item_id))


def mark_feed_checked(feed_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE rss_feeds SET last_checked_at = ? WHERE id = ?",
            (_now_string(), feed_id),
        )


def refresh_rss_content_types():
    with get_connection() as conn:
        items = conn.execute("SELECT id, url, content_type FROM rss_items").fetchall()
        for item in items:
            content_type = classify_content_type(item["url"], fallback=item["content_type"])
            if content_type == item["content_type"]:
                continue
            conn.execute(
                "UPDATE rss_items SET content_type = ? WHERE id = ?",
                (content_type, item["id"]),
            )
            conn.execute(
                "UPDATE posts SET source_type = ? WHERE rss_item_id = ?",
                (content_type, item["id"]),
            )


def _record_feed_check(feed_id, created, skipped, errors):
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE rss_feeds
            SET last_checked_at = ?,
                last_check_status = ?,
                last_check_message = ?,
                last_created_count = ?,
                last_skipped_count = ?,
                last_error_count = ?
            WHERE id = ?
            """,
            (
                _now_string(),
                _status_for_errors(errors),
                _message_for_result(created, skipped, errors),
                created,
                skipped,
                len(errors),
                feed_id,
            ),
        )


def _feed_with_health(feed):
    feed_data = dict(feed)
    status = feed_data.get("last_check_status") or "Never checked"
    checked_at = _parse_check_time(feed_data.get("last_checked_at"))

    if status == "Error":
        badge = "Error"
    elif checked_at is None:
        badge = "Never checked"
    elif datetime.now() - checked_at > timedelta(hours=FRESHNESS_WINDOW_HOURS):
        badge = "Needs check"
    else:
        badge = "Up to date"

    feed_data["health_badge"] = badge
    feed_data["health_class"] = badge.lower().replace(" ", "-")
    return feed_data


def _status_for_errors(errors):
    return "Error" if errors else "OK"


def _message_for_result(created, skipped, errors):
    if errors:
        return errors[0]
    return f"{created} draft(s) created, {skipped} item(s) skipped."


def _now_string():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_check_time(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _item_exists(conn, feed_id, guid):
    row = conn.execute(
        "SELECT id FROM rss_items WHERE feed_id = ? AND item_guid = ?",
        (feed_id, guid),
    ).fetchone()
    return row is not None


def _url_exists(conn, url):
    variants = _url_variants(url)
    placeholders = ",".join("?" for _ in variants)
    row = conn.execute(f"SELECT id FROM rss_items WHERE url IN ({placeholders})", variants).fetchone()
    return row is not None


def _url_variants(url):
    clean_url = (url or "").strip()
    without_trailing_slash = clean_url.rstrip("/")
    variants = [clean_url]
    if without_trailing_slash and without_trailing_slash != clean_url:
        variants.append(without_trailing_slash)
    elif clean_url:
        variants.append(clean_url + "/")
    return variants


def _remember_item(conn, feed_id, guid, title, url, image_url, content_type, post_id):
    row = conn.execute(
        "SELECT id FROM rss_items WHERE feed_id = ? AND item_guid = ?",
        (feed_id, guid),
    ).fetchone()
    if row:
        return row["id"]
    return insert_and_get_id(
        conn,
        """
        INSERT INTO rss_items (feed_id, item_guid, title, url, image_url, content_type, post_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (feed_id, guid, title, url, image_url, content_type, post_id),
    )


def _create_rss_draft(conn, feed, entry, platform, rss_item_id, content_type):
    return insert_and_get_id(
        conn,
        """
        INSERT INTO posts (title, content, hashtags, platform, content_format, rss_item_id, source_type, scheduled_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _trim(entry["title"], 120),
            _draft_content(entry, feed, platform, content_type),
            feed["default_hashtags"] or "",
            platform,
            default_content_format(platform),
            rss_item_id,
            content_type,
            "",
            "Draft",
        ),
    )


def _parse_rss(root):
    entries = []
    media_ns = {"media": "http://search.yahoo.com/mrss/"}
    for item in root.findall(".//item"):
        title = _text(item, "title")
        link = _text(item, "link")
        guid = _text(item, "guid") or link or _hash(title)
        summary = _text(item, "description")
        image_url = _rss_image_url(item, summary, media_ns)
        if title and link:
            entries.append({"title": title, "link": link, "guid": guid, "summary": summary, "image_url": image_url})
    return entries


def _parse_atom(root):
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = []
    for item in root.findall(".//atom:entry", ns):
        title = _text(item, "atom:title", ns)
        link_el = item.find("atom:link", ns)
        link = link_el.attrib.get("href", "") if link_el is not None else ""
        guid = _text(item, "atom:id", ns) or link or _hash(title)
        summary = _text(item, "atom:summary", ns) or _text(item, "atom:content", ns)
        image_url = _first_image_from_html(summary)
        if title and link:
            entries.append({"title": title, "link": link, "guid": guid, "summary": summary, "image_url": image_url})
    return entries


def _rss_image_url(item, summary, media_ns):
    media = item.find("media:content", media_ns)
    if media is None:
        media = item.find("media:thumbnail", media_ns)
    if media is not None and media.attrib.get("url"):
        return media.attrib["url"].strip()
    enclosure = item.find("enclosure")
    if enclosure is not None and enclosure.attrib.get("type", "").startswith("image/"):
        return enclosure.attrib.get("url", "").strip()
    return _first_image_from_html(summary)


def _first_image_from_html(value):
    if not value:
        return ""
    match = re.search(r"<img[^>]+src=[\"']([^\"']+)[\"']", value, re.IGNORECASE)
    return unescape(match.group(1)).strip() if match else ""


def _draft_content(entry, feed=None, platform="", content_type="Regular"):
    copy_template = (feed or {}).get("copy_template", "").strip()
    if copy_template:
        return _render_copy_template(copy_template, feed, entry, platform, content_type)

    summary = _trim(_clean_summary(entry.get("summary") or ""), 800)
    if summary:
        return f"{summary}\n\nSource: {entry['link']}"
    return f"Source: {entry['link']}"


def _render_copy_template(template, feed, entry, platform, content_type):
    summary = _clean_summary(entry.get("summary") or "")
    values = {
        "title": entry.get("title", ""),
        "summary": summary,
        "excerpt": summary,
        "url": entry.get("link", ""),
        "source": entry.get("link", ""),
        "feed": (feed or {}).get("name", ""),
        "platform": platform,
        "hashtags": (feed or {}).get("default_hashtags", ""),
        "type": source_type_label(content_type),
    }

    def replace(match):
        value = values.get(match.group(1).lower(), "")
        limit = match.group(2)
        if limit and value:
            value = _trim(value, int(limit))
        return value

    rendered = re.sub(r"\{([a-z_]+)(?::(\d{1,4}))?\}", replace, template)
    return _trim(rendered.strip(), 2200) or _draft_content(entry)


def _text(element, selector, ns=None):
    child = element.find(selector, ns or {})
    if child is None or child.text is None:
        return ""
    return child.text.strip()


def _trim(value, limit):
    value = value.strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3].rstrip() + "..."


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _clean_summary(value):
    value = unescape(value)
    value = re.sub(r"<[^>]+>", " ", value)
    return " ".join(value.split())


def classify_content_type(url, fallback="Regular"):
    path = _normalize_slug(urlparse(url).path)
    segments = [segment for segment in re.split(r"[-_/]+", path) if segment]
    if any(segment in {"noticia", "noticias"} for segment in segments):
        return "News"
    return fallback or "Regular"


def _normalize_slug(value):
    value = unquote(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.lower()
