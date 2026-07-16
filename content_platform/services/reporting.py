from collections import Counter
from datetime import datetime, timedelta
from email.message import EmailMessage
import os
import smtplib
import ssl

from ..database import get_connection
from .analytics import build_status_counts
from .clock import app_now
from .scheduler import get_all_posts, get_logs


def build_dashboard_report(limit=12):
    posts = get_all_posts()
    upcoming = get_upcoming_items(limit=limit)
    logs = get_logs()[:8]
    platform_counts = Counter(post["platform"] for post in posts)
    status_counts = build_status_counts(posts)

    lines = [
        "Supernova - Daily Report",
        f"Generated at: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "Dashboard",
        f"- Draft: {status_counts['Draft']}",
        f"- Scheduled: {status_counts['Scheduled']}",
        f"- Published: {status_counts['Published']}",
        f"- Failed: {status_counts['Failed']}",
        "",
        "Platforms",
    ]

    if platform_counts:
        for platform, count in platform_counts.most_common():
            lines.append(f"- {platform}: {count}")
    else:
        lines.append("- No platform data yet.")

    lines.extend(["", "Upcoming posts and recycled schedules"])
    if upcoming:
        for item in upcoming:
            lines.append(
                f"- {item['scheduled_at']} | {item['platform']} | "
                f"{item['content_format']} | {item['title']} | {item['source']}"
            )
    else:
        lines.append("- No upcoming scheduled items.")

    lines.extend(["", "Recent automation logs"])
    if logs:
        for log in logs:
            post_title = log["post_title"] or "-"
            lines.append(f"- {log['created_at']} | {log['level']} | {post_title} | {log['message']}")
    else:
        lines.append("- No logs yet.")

    return "\n".join(lines)


def build_daily_publication_report(report_date=None):
    report_day = report_date or app_now().date()
    items = get_daily_publication_items(report_day)

    lines = [
        f"Supernova - Posts for {report_day.isoformat()}",
        f"Generated at: {app_now().strftime('%Y-%m-%d %H:%M')}",
        "",
        "Publishing plan",
    ]

    if items:
        for item in items:
            scheduled_at = _display_time(item["scheduled_at"])
            lines.append(
                f"- {scheduled_at} | {item['platform']} | {item['content_format']} | "
                f"{item['source_type']} | {item['status']} | {item['title']} | {item['source']}"
            )
    else:
        lines.append("- No posts scheduled for today.")

    lines.extend(
        [
            "",
            "Operational note",
            "- Check Supernova logs after publishing windows to confirm each API returned success.",
        ]
    )
    return "\n".join(lines)


def get_upcoming_items(limit=12):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                posts.title,
                posts.platform,
                posts.content_format,
                COALESCE(post_schedules.scheduled_at, posts.scheduled_at) AS scheduled_at,
                CASE
                    WHEN post_schedules.id IS NULL THEN 'primary schedule'
                    ELSE 'recycled schedule'
                END AS source
            FROM posts
            LEFT JOIN post_schedules ON post_schedules.post_id = posts.id
                AND post_schedules.status = 'Scheduled'
            WHERE posts.status = 'Scheduled'
              AND COALESCE(post_schedules.scheduled_at, posts.scheduled_at) IS NOT NULL
              AND COALESCE(post_schedules.scheduled_at, posts.scheduled_at) != ''
            ORDER BY scheduled_at ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def get_daily_publication_items(report_day):
    start = datetime.combine(report_day, datetime.min.time()).strftime("%Y-%m-%dT%H:%M")
    end = datetime.combine(report_day + timedelta(days=1), datetime.min.time()).strftime("%Y-%m-%dT%H:%M")

    with get_connection() as conn:
        return conn.execute(
            """
            SELECT
                posts.title,
                posts.platform,
                posts.content_format,
                posts.source_type,
                posts.status,
                posts.scheduled_at AS scheduled_at,
                'primary schedule' AS source
            FROM posts
            WHERE posts.scheduled_at IS NOT NULL
              AND posts.scheduled_at != ''
              AND posts.scheduled_at >= ?
              AND posts.scheduled_at < ?
            UNION ALL
            SELECT
                posts.title,
                posts.platform,
                posts.content_format,
                posts.source_type,
                post_schedules.status AS status,
                post_schedules.scheduled_at AS scheduled_at,
                'recycled schedule' AS source
            FROM post_schedules
            JOIN posts ON posts.id = post_schedules.post_id
            WHERE post_schedules.scheduled_at >= ?
              AND post_schedules.scheduled_at < ?
            ORDER BY scheduled_at ASC, platform ASC
            """,
            (start, end, start, end),
        ).fetchall()


def send_dashboard_report():
    _send_email(
        os.environ.get("REPORT_EMAIL_SUBJECT") or "Supernova report",
        build_dashboard_report(),
    )


def send_daily_publication_report(report_date=None):
    report_day = report_date or app_now().date()
    _send_email(
        os.environ.get("DAILY_REPORT_EMAIL_SUBJECT") or f"Supernova posts for {report_day.isoformat()}",
        build_daily_publication_report(report_day),
    )


def _send_email(subject, body):
    required = ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "REPORT_TO_EMAIL"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing email environment variables: " + ", ".join(missing))

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    from_email = os.environ.get("SMTP_FROM_EMAIL") or smtp_username
    to_email = os.environ["REPORT_TO_EMAIL"]

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(body)

    if smtp_port == 465:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context) as server:
            server.login(smtp_username, smtp_password)
            server.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls(context=ssl.create_default_context())
            server.login(smtp_username, smtp_password)
            server.send_message(message)


def _display_time(value):
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).strftime("%H:%M")
    except ValueError:
        return value
