"""Read-only projection of the scheduler's pending occurrences."""
from datetime import datetime

from ..database import get_connection
from .clock import app_now
from .media import get_media_for_posts
from .scheduler import get_all_posts
from .schedules import get_schedules_for_posts


def list_scheduled_occurrences():
    posts = get_all_posts()
    ids = [post['id'] for post in posts]
    schedules = get_schedules_for_posts(ids)
    media = get_media_for_posts(ids)
    with get_connection() as conn:
        sources = {row['id']: row['url'] for row in conn.execute('SELECT id, url FROM rss_items').fetchall()}
        errors = {}
        for row in conn.execute("SELECT post_id, message FROM logs WHERE level = 'ERROR' ORDER BY id ASC").fetchall():
            errors[row['post_id']] = row['message']
    tz = app_now().tzinfo
    result = []
    for post in posts:
        occurrences = schedules.get(post['id'], [])
        # Like get_due_posts, primary dates apply only without occurrence rows.
        if not occurrences and post['status'] == 'Scheduled':
            occurrences = [{'id': None, 'status': 'Scheduled', 'scheduled_at': post['scheduled_at']}]
        for occurrence in occurrences:
            if occurrence['status'] != 'Scheduled':
                continue
            raw_date = occurrence['scheduled_at']
            date_error = ''
            try:
                date = datetime.fromisoformat(raw_date)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=tz)
                date = date.astimezone(tz)
                iso_date = date.isoformat()
                label = date.strftime('%d/%m/%Y %H:%M %Z (UTC%z)')
            except (ValueError, TypeError):
                iso_date = None
                label = raw_date or 'Sem data'
                date_error = 'Data agendada ausente ou inválida.'
            result.append({
                'post_id': post['id'], 'schedule_id': occurrence['id'],
                'title': post['title'], 'content': post['content'][:260],
                'source_type': post['source_type'], 'url': sources.get(post['rss_item_id'], ''),
                'platform': post['platform'], 'content_format': post['content_format'],
                'media': [{'name': item['original_filename'], 'type': item['media_type']}
                          for item in media.get(post['id'], [])],
                'scheduled_at': iso_date, 'scheduled_label': label, 'timezone': str(tz),
                'status': occurrence['status'], 'post_status': post['status'],
                'error': errors.get(post['id'], ''), 'date_error': date_error,
            })
    return sorted(result, key=lambda row: (
        row['scheduled_at'] is None,
        datetime.fromisoformat(row['scheduled_at']).timestamp() if row['scheduled_at'] else 0,
        row['post_id'], row['schedule_id'] or 0,
    ))
