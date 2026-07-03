from datetime import datetime
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
from ..models import default_content_format
from .scheduler import add_log


USER_AGENT = "ContentAutomationPlatform/1.0"


def list_feeds():
    with get_connection() as conn:
        return conn.execute("SELECT * FROM rss_feeds ORDER BY created_at DESC").fetchall()


def create_feed(name, url, target_platforms, default_hashtags):
    content_type = classify_content_type(url)
    with get_connection() as conn:
        existing = conn.execute("SELECT id FROM rss_feeds WHERE url = ?", (url,)).fetchone()
        if existing:
            return False
        conn.execute(
            """
            INSERT INTO rss_feeds (name, url, target_platforms, default_hashtags, content_type)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, url, ",".join(target_platforms), default_hashtags, content_type),
        )

    return True


def delete_feed(feed_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM rss_feeds WHERE id = ?", (feed_id,))


def check_all_feeds():
    created = 0
    skipped = 0
    errors = []
    for feed in list_feeds():
        if not feed["is_active"]:
            continue
        try:
            result = check_feed(feed)
        except Exception as exc:
            message = f"{feed['name']}: {exc}"
            try:
                add_log(None, "ERROR", f"RSS check failed: {message}")
            except Exception:
                pass
            errors.append(message)
            continue
        created += result["created"]
        skipped += result["skipped"]
        errors.extend(result["errors"])
    return {"created": created, "skipped": skipped, "errors": errors}


def check_feed(feed):
    created = 0
    skipped = 0
    errors = []

    try:
        entries = fetch_feed_entries(feed["url"])
    except (URLError, ET.ParseError, TimeoutError, ValueError) as exc:
        errors.append(f"{feed['name']}: {exc}")
        return {"created": created, "skipped": skipped, "errors": errors}

    platforms = [item.strip() for item in feed["target_platforms"].split(",") if item.strip()]
    max_entries = int(os.environ.get("RSS_MAX_ENTRIES_PER_FEED", "10"))
    with get_connection() as conn:
        for entry in entries[:max_entries]:
            guid = entry["guid"]
            if _item_exists(conn, feed["id"], guid):
                skipped += 1
                continue

            content_type = classify_content_type(entry["link"], fallback=feed["content_type"])
            rss_item_id = _remember_item(conn, feed["id"], guid, entry["title"], entry["link"], content_type, None)
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
            "UPDATE rss_feeds SET last_checked_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), feed["id"]),
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


def remember_item(feed_id, guid, title, url, content_type, post_id):
    with get_connection() as conn:
        return _remember_item(conn, feed_id, guid, title, url, content_type, post_id)


def update_item_post(rss_item_id, post_id):
    with get_connection() as conn:
        conn.execute("UPDATE rss_items SET post_id = ? WHERE id = ?", (post_id, rss_item_id))


def mark_feed_checked(feed_id):
    with get_connection() as conn:
        conn.execute(
            "UPDATE rss_feeds SET last_checked_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), feed_id),
        )


def _item_exists(conn, feed_id, guid):
    row = conn.execute(
        "SELECT id FROM rss_items WHERE feed_id = ? AND item_guid = ?",
        (feed_id, guid),
    ).fetchone()
    return row is not None


def _remember_item(conn, feed_id, guid, title, url, content_type, post_id):
    row = conn.execute(
        "SELECT id FROM rss_items WHERE feed_id = ? AND item_guid = ?",
        (feed_id, guid),
    ).fetchone()
    if row:
        return row["id"]
    return insert_and_get_id(
        conn,
        """
        INSERT INTO rss_items (feed_id, item_guid, title, url, content_type, post_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (feed_id, guid, title, url, content_type, post_id),
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
            _draft_content(entry),
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
    for item in root.findall(".//item"):
        title = _text(item, "title")
        link = _text(item, "link")
        guid = _text(item, "guid") or link or _hash(title)
        summary = _text(item, "description")
        if title and link:
            entries.append({"title": title, "link": link, "guid": guid, "summary": summary})
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
        if title and link:
            entries.append({"title": title, "link": link, "guid": guid, "summary": summary})
    return entries


def _draft_content(entry):
    summary = _trim(_clean_summary(entry.get("summary") or ""), 800)
    if summary:
        return f"{summary}\n\nSource: {entry['link']}"
    return f"Source: {entry['link']}"


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
    if re.search(r"(^|[-_/])noticias?($|[-_/])", path) or re.search(r"(^|[-_/])noticia($|[-_/])", path):
        return "News"
    return fallback or "Regular"


def _normalize_slug(value):
    value = unquote(value)
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    return value.lower()
