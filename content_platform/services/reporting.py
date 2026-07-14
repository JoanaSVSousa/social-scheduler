from collections import Counter
from datetime import datetime
from email.message import EmailMessage
import os
import smtplib
import ssl

from ..database import get_connection
from .analytics import build_status_counts
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


def send_dashboard_report():
    required = ["SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "REPORT_TO_EMAIL"]
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing email environment variables: " + ", ".join(missing))

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ["SMTP_USERNAME"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    from_email = os.environ.get("SMTP_FROM_EMAIL", smtp_username)
    to_email = os.environ["REPORT_TO_EMAIL"]

    message = EmailMessage()
    message["Subject"] = os.environ.get("REPORT_EMAIL_SUBJECT", "Supernova report")
    message["From"] = from_email
    message["To"] = to_email
    message.set_content(build_dashboard_report())

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
