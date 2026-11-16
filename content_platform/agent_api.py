"""Versioned, narrowly scoped agent access; browser sessions confer no API access."""
import hashlib
import hmac
import json
import os
from datetime import datetime
from uuid import uuid4

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .database import get_connection
from .models import (
    FORMAT_MEDIA_RULES, PLATFORM_CONTENT_FORMATS, PLATFORM_CONTENT_LIMITS,
    PLATFORMS, Post, default_content_format,
)
from .services.clock import app_now
from .services.publisher import publish_post_now
from .services.rss_groups import delete_rss_group
from .services.scheduler import add_log
from .services.scheduled_view import list_scheduled_occurrences

bp = Blueprint('agent_api', __name__, url_prefix='/api')
CLASSIFICATIONS = {'all_green': 'Regular', 'news': 'News'}
REVERSE = {value: key for key, value in CLASSIFICATIONS.items()}


class ApiError(Exception):
    def __init__(self, code, status):
        self.code, self.status = code, status


@bp.before_request
def authenticate():
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer ') or len(authorization) > 1024:
        raise ApiError('unauthorized', 401)
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    g.can_classify = False
    g.can_manage_posts = False
    matched = False
    for variable, capability in [
        ('SUPERNOVA_AGENT_READ_TOKEN_SHA256', 'read'),
        ('SUPERNOVA_AGENT_CLASSIFY_TOKEN_SHA256', 'classify'),
        ('SUPERNOVA_AGENT_MANAGE_TOKEN_SHA256', 'manage'),
    ]:
        configured = os.environ.get(variable, '')
        if len(configured) == 64 and hmac.compare_digest(digest, configured):
            matched = True
            g.can_classify = g.can_classify or capability in {'classify', 'manage'}
            g.can_manage_posts = g.can_manage_posts or capability == 'manage'
    if not matched:
        raise ApiError('unauthorized', 401)
    # Stable audit identity without storing a usable credential.
    g.agent_id = 'agent-' + digest[:16]
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not (g.can_classify or g.can_manage_posts):
        raise ApiError('forbidden', 403)


@bp.after_request
def prevent_caching(response):
    response.headers['Cache-Control'] = 'no-store'
    if response.status_code == 401:
        response.headers['WWW-Authenticate'] = 'Bearer'
    return response


@bp.errorhandler(ApiError)
def api_error(error):
    return jsonify(error=error.code), error.status


@bp.errorhandler(Exception)
def unexpected_error(error):
    if isinstance(error, HTTPException):
        return jsonify(error=error.name), error.code
    current_app.logger.exception('Agent API request failed')
    return jsonify(error='service_unavailable'), 503


def version(post):
    """Opaque row revision detects changes from existing UI/worker writers too."""
    return hashlib.sha256(json.dumps(dict(post), sort_keys=True, default=str).encode()).hexdigest()


def read_post(conn, post_id, lock=False):
    suffix = ' FOR UPDATE' if lock and conn.dialect == 'postgres' else ''
    post = conn.execute('SELECT * FROM posts WHERE id = ?' + suffix, (post_id,)).fetchone()
    if post is None:
        raise ApiError('post_not_found', 404)
    return post


def serialize(conn, post):
    article = conn.execute('SELECT id, title, url FROM rss_items WHERE id = ?',
                           (post['rss_item_id'],)).fetchone() if post['rss_item_id'] else None
    media = conn.execute('SELECT id, original_filename, media_type, public_url FROM media_assets WHERE post_id = ? ORDER BY id',
                         (post['id'],)).fetchall()
    schedules = conn.execute('SELECT id, scheduled_at, status, published_at FROM post_schedules WHERE post_id = ? ORDER BY scheduled_at, id',
                             (post['id'],)).fetchall()
    return {
        'id': post['id'], 'title': post['title'], 'status': post['status'].lower(),
        'classification': REVERSE.get(post['source_type']), 'source_type': post['source_type'],
        'article_id': article['id'] if article else None,
        'article_url': article['url'] if article else None,
        'article_title': article['title'] if article else None,
        'platform': post['platform'], 'content_format': post['content_format'],
        'copy': post['content'], 'hashtags': post['hashtags'],
        'media': [dict(item) for item in media], 'scheduled_at': post['scheduled_at'],
        'timezone': str(app_now().tzinfo), 'occurrences': [dict(item) for item in schedules],
        'created_at': post['created_at'], 'updated_at': post['updated_at'], 'version': version(post),
    }


def integer_arg(name, default, maximum=None):
    raw = request.args.get(name, str(default))
    if not raw.isascii() or not raw.isdigit() or int(raw) < 1:
        raise ApiError('invalid_' + name, 400)
    value = int(raw)
    if value > (maximum or 2147483647):
        raise ApiError('invalid_' + name, 400)
    return value


@bp.get('/version')
def api_version():
    return jsonify(api_version='1', revision=os.environ.get('RENDER_GIT_COMMIT', 'local'),
                   capabilities=(['read_posts', 'read_scheduled', 'classify_posts', 'manage_posts', 'publish_posts', 'delete_rss_articles']
                                 if g.can_manage_posts else
                                 ['read_posts', 'read_scheduled', 'classify_posts'] if g.can_classify else
                                 ['read_posts', 'read_scheduled']))


@bp.get('/posts')
def posts():
    allowed = {'status', 'classification', 'article_id', 'page', 'per_page'}
    if set(request.args) - allowed:
        raise ApiError('unknown_filter', 400)
    page, per_page = integer_arg('page', 1), integer_arg('per_page', 50, 100)
    clauses, params = [], []
    status = request.args.get('status')
    if status is not None:
        if status not in {'draft', 'scheduled', 'published', 'failed'}:
            raise ApiError('invalid_status', 400)
        clauses.append('status = ?')
        params.append(status.title())
    classification = request.args.get('classification')
    if classification is not None:
        if classification not in CLASSIFICATIONS:
            raise ApiError('invalid_classification', 400)
        clauses.append('source_type = ?')
        params.append(CLASSIFICATIONS[classification])
    if 'article_id' in request.args:
        clauses.append('rss_item_id = ?')
        params.append(integer_arg('article_id', 1))
    where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
    with get_connection() as conn:
        total = conn.execute('SELECT COUNT(*) AS count FROM posts' + where, params).fetchone()['count']
        rows = conn.execute('SELECT * FROM posts' + where + ' ORDER BY id LIMIT ? OFFSET ?',
                            params + [per_page, (page - 1) * per_page]).fetchall()
        return jsonify(posts=[serialize(conn, post) for post in rows], total=total,
                       page=page, per_page=per_page)


@bp.get('/posts/<int:post_id>')
@bp.get('/posts/<int:post_id>/verify')
def post_detail(post_id):
    with get_connection() as conn:
        return jsonify(post=serialize(conn, read_post(conn, post_id)))


@bp.patch('/posts/<int:post_id>/classification')
def classify(post_id):
    if not g.can_classify:
        raise ApiError('forbidden', 403)
    if request.content_length and request.content_length > 8192:
        raise ApiError('payload_too_large', 413)
    body = request.get_json(silent=True)
    required = {'classification', 'reason', 'expected_version', 'client_request_id'}
    if not isinstance(body, dict) or set(body) != required:
        raise ApiError('invalid_payload', 400)
    if any(not isinstance(body[key], str) for key in required):
        raise ApiError('invalid_payload', 400)
    if body['classification'] not in CLASSIFICATIONS:
        raise ApiError('invalid_classification', 400)
    if not 1 <= len(body['reason'].strip()) <= 1000 or not 1 <= len(body['client_request_id']) <= 128:
        raise ApiError('invalid_payload', 400)
    if len(body['expected_version']) != 64:
        raise ApiError('invalid_version', 400)
    fingerprint = hashlib.sha256(json.dumps({'post_id': post_id, **body}, sort_keys=True).encode()).hexdigest()
    with get_connection() as conn:
        if conn.dialect == 'sqlite':
            conn.execute('BEGIN IMMEDIATE')
        elif conn.dialect == 'postgres':
            # Serialize retries even when the same key is accidentally reused for another post.
            key = int.from_bytes(hashlib.sha256((g.agent_id + ':' + body['client_request_id']).encode()).digest()[:8], 'big', signed=True)
            conn.execute('SELECT pg_advisory_xact_lock(?)', (key,))
        previous = conn.execute('SELECT * FROM agent_operations WHERE agent_id = ? AND client_request_id = ?',
                                (g.agent_id, body['client_request_id'])).fetchone()
        if previous:
            if previous['request_hash'] != fingerprint:
                raise ApiError('idempotency_conflict', 409)
            original = json.loads(previous['response_json'])
            return jsonify(**original, already_applied=True)
        post = read_post(conn, post_id, lock=True)
        if version(post) != body['expected_version']:
            raise ApiError('version_conflict', 409)
        before = REVERSE.get(post['source_type'])
        changed = post['source_type'] != CLASSIFICATIONS[body['classification']]
        if changed:
            conn.execute('UPDATE posts SET source_type = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?',
                         (CLASSIFICATIONS[body['classification']], post_id))
        updated = serialize(conn, read_post(conn, post_id))
        operation_id = str(uuid4())
        response = {'ok': True, 'operation_id': operation_id, 'post_id': post_id,
                    'previous_classification': before, 'classification': updated['classification'],
                    'version': updated['version'], 'changed': changed, 'readback': True, 'post': updated}
        conn.execute('''INSERT INTO agent_operations
            (operation_id, agent_id, client_request_id, request_hash, post_id, reason, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (operation_id, g.agent_id, body['client_request_id'], fingerprint, post_id,
             body['reason'], json.dumps(response)))
        conn.execute('INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)',
                     (post_id, 'INFO', f'Agent classification operation {operation_id}: {before} -> {updated["classification"]}'))
    return jsonify(**response, already_applied=False)


def _require_manage():
    if not g.can_manage_posts:
        raise ApiError('forbidden', 403)


def _operation_lock(conn, client_request_id):
    if conn.dialect == 'sqlite':
        conn.execute('BEGIN IMMEDIATE')
    elif conn.dialect == 'postgres':
        key = int.from_bytes(hashlib.sha256((g.agent_id + ':' + client_request_id).encode()).digest()[:8], 'big', signed=True)
        conn.execute('SELECT pg_advisory_xact_lock(?)', (key,))


def _existing_operation(conn, client_request_id, fingerprint):
    previous = conn.execute('SELECT request_hash, response_json FROM agent_operations WHERE agent_id = ? AND client_request_id = ?',
                            (g.agent_id, client_request_id)).fetchone()
    if not previous:
        return None
    if previous['request_hash'] != fingerprint:
        raise ApiError('idempotency_conflict', 409)
    return json.loads(previous['response_json'])


def _validate_post_content(payload, *, creating):
    allowed = {'title', 'copy', 'hashtags', 'source_type', 'platform', 'content_format', 'scheduled_at'}
    required = {'title', 'copy', 'platform'} if creating else set()
    if not isinstance(payload, dict) or set(payload) - allowed or not required.issubset(payload):
        raise ApiError('invalid_payload', 400)
    if creating:
        for key in ('title', 'copy', 'platform', 'hashtags', 'source_type', 'content_format'):
            if key in payload and not isinstance(payload[key], str):
                raise ApiError('invalid_payload', 400)
        if 'scheduled_at' in payload and payload['scheduled_at'] is not None and not isinstance(payload['scheduled_at'], str):
            raise ApiError('invalid_payload', 400)
    for key in payload:
        if key == 'scheduled_at' and payload[key] is None:
            continue
        if not isinstance(payload[key], str):
            raise ApiError('invalid_payload', 400)
    if creating:
        platform = payload['platform']
        title = payload['title'].strip()
        copy = payload['copy'].strip()
        hashtags = payload.get('hashtags', '').strip()
        source_type = payload.get('source_type', 'Regular')
        content_format = payload.get('content_format') or default_content_format(platform)
        scheduled_at = payload.get('scheduled_at')
    else:
        platform = None
        title = payload.get('title')
        copy = payload.get('copy')
        hashtags = payload.get('hashtags')
        source_type = payload.get('source_type')
        content_format = payload.get('content_format')
        scheduled_at = payload.get('scheduled_at')
    if creating and platform not in PLATFORMS:
        raise ApiError('invalid_platform', 400)
    if creating and (not title or len(title) > 120 or not copy):
        raise ApiError('invalid_content', 400)
    if creating and (source_type not in {'Regular', 'News'} or content_format not in PLATFORM_CONTENT_FORMATS.get(platform, [])):
        raise ApiError('invalid_content_format', 400)
    if creating and FORMAT_MEDIA_RULES.get(content_format, {}).get('media_required'):
        raise ApiError('media_upload_not_supported', 400)
    if creating and len(hashtags) > 400:
        raise ApiError('invalid_hashtags', 400)
    if creating and len(copy) + (len(hashtags) + 2 if hashtags else 0) > PLATFORM_CONTENT_LIMITS.get(platform, 2200):
        raise ApiError('content_too_long', 400)
    if scheduled_at:
        try:
            parsed = datetime.fromisoformat(scheduled_at.replace('Z', '+00:00'))
        except ValueError as exc:
            raise ApiError('invalid_scheduled_at', 400) from exc
        local_now = app_now()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=local_now.tzinfo)
        if parsed <= local_now:
            raise ApiError('scheduled_at_must_be_future', 400)
        scheduled_at = parsed.astimezone(local_now.tzinfo).replace(tzinfo=None).isoformat(timespec='minutes')
    return {
        'title': title, 'copy': copy, 'hashtags': hashtags, 'source_type': source_type,
        'content_format': content_format, 'scheduled_at': scheduled_at,
    }


@bp.post('/posts')
def create_agent_post():
    _require_manage()
    payload = request.get_json(silent=True)
    if request.content_length and request.content_length > 16384:
        raise ApiError('payload_too_large', 413)
    if not isinstance(payload, dict) or not isinstance(payload.get('client_request_id'), str) or not 1 <= len(payload['client_request_id']) <= 128:
        raise ApiError('invalid_payload', 400)
    if set(payload) - {'title', 'copy', 'hashtags', 'source_type', 'platform', 'content_format', 'scheduled_at', 'client_request_id'}:
        raise ApiError('invalid_payload', 400)
    post_fields = _validate_post_content({key: value for key, value in payload.items() if key != 'client_request_id'}, creating=True)
    request_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    status = 'Scheduled' if post_fields['scheduled_at'] else 'Draft'
    with get_connection() as conn:
        _operation_lock(conn, payload['client_request_id'])
        previous = _existing_operation(conn, payload['client_request_id'], request_hash)
        if previous:
            return jsonify({**previous, 'already_applied': True})
        post = Post(title=post_fields['title'], content=post_fields['copy'], hashtags=post_fields['hashtags'],
                    platform=payload['platform'], content_format=post_fields['content_format'],
                    scheduled_at=post_fields['scheduled_at'], status=status, source_type=post_fields['source_type'])
        from .database import insert_and_get_id
        post_id = insert_and_get_id(conn, '''INSERT INTO posts
            (title, content, hashtags, platform, content_format, rss_item_id, source_type, scheduled_at, status)
            VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?)''',
            (post.title, post.content, post.hashtags, post.platform, post.content_format,
             post.source_type, post.scheduled_at, post.status))
        created = read_post(conn, post_id)
        response = {'ok': True, 'post': serialize(conn, created), 'already_applied': False}
        operation_id = str(uuid4())
        conn.execute('''INSERT INTO agent_operations
            (operation_id, agent_id, client_request_id, request_hash, post_id, reason, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (operation_id, g.agent_id, payload['client_request_id'], request_hash, post_id,
             'Agent created post', json.dumps(response)))
        conn.execute('INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)',
                     (post_id, 'INFO', f'Agent created post ({operation_id}).'))
    return jsonify(**response), 201


@bp.patch('/posts/<int:post_id>')
def update_agent_post(post_id):
    _require_manage()
    payload = request.get_json(silent=True)
    required = {'expected_version', 'client_request_id'}
    editable = {'title', 'copy', 'hashtags', 'scheduled_at'}
    if request.content_length and request.content_length > 16384:
        raise ApiError('payload_too_large', 413)
    if (not isinstance(payload, dict) or not required.issubset(payload)
            or set(payload) - required - editable
            or not editable.intersection(payload)
            or not isinstance(payload['expected_version'], str)
            or len(payload['expected_version']) != 64
            or not isinstance(payload['client_request_id'], str)
            or not 1 <= len(payload['client_request_id']) <= 128):
        raise ApiError('invalid_payload', 400)
    for key, value in payload.items():
        if key not in {'scheduled_at'} or value is not None:
            if not isinstance(value, str):
                raise ApiError('invalid_payload', 400)
    request_hash = hashlib.sha256(json.dumps({'post_id': post_id, **payload}, sort_keys=True).encode()).hexdigest()
    with get_connection() as conn:
        _operation_lock(conn, payload['client_request_id'])
        previous = _existing_operation(conn, payload['client_request_id'], request_hash)
        if previous:
            return jsonify({**previous, 'already_applied': True})
        post = read_post(conn, post_id, lock=True)
        if version(post) != payload['expected_version']:
            raise ApiError('version_conflict', 409)
        if post['status'] not in {'Draft', 'Scheduled', 'Failed'}:
            raise ApiError('post_not_editable', 409)
        updates = {}
        for field in editable.intersection(payload):
            updates[field] = payload[field]
        title = updates.get('title', post['title']).strip()
        copy = updates.get('copy', post['content']).strip()
        hashtags = updates.get('hashtags', post['hashtags'] or '').strip()
        scheduled_at = updates.get('scheduled_at', post['scheduled_at'])
        if not title or len(title) > 120 or not copy or len(hashtags) > 400:
            raise ApiError('invalid_content', 400)
        if len(copy) + (len(hashtags) + 2 if hashtags else 0) > PLATFORM_CONTENT_LIMITS.get(post['platform'], 2200):
            raise ApiError('content_too_long', 400)
        if scheduled_at:
            normalized = _validate_post_content({'scheduled_at': scheduled_at}, creating=False)['scheduled_at']
            scheduled_at = normalized
        next_status = 'Scheduled' if scheduled_at else 'Draft'
        conn.execute('''UPDATE posts SET title=?, content=?, hashtags=?, scheduled_at=?, status=?, updated_at=CURRENT_TIMESTAMP
                        WHERE id=?''', (title, copy, hashtags, scheduled_at, next_status, post_id))
        updated = serialize(conn, read_post(conn, post_id))
        response = {'ok': True, 'post': updated, 'already_applied': False}
        operation_id = str(uuid4())
        conn.execute('''INSERT INTO agent_operations
            (operation_id, agent_id, client_request_id, request_hash, post_id, reason, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (operation_id, g.agent_id, payload['client_request_id'], request_hash, post_id,
             'Agent edited post', json.dumps(response)))
        conn.execute('INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)',
                     (post_id, 'INFO', f'Agent edited post ({operation_id}).'))
    return jsonify(**response)


@bp.post('/posts/<int:post_id>/publish')
def publish_agent_post(post_id):
    _require_manage()
    payload = request.get_json(silent=True)
    required = {'expected_version', 'client_request_id', 'reason'}
    if not isinstance(payload, dict) or set(payload) != required or any(not isinstance(payload[k], str) for k in required):
        raise ApiError('invalid_payload', 400)
    if (len(payload['expected_version']) != 64 or not 1 <= len(payload['client_request_id']) <= 128
            or not 1 <= len(payload['reason'].strip()) <= 1000):
        raise ApiError('invalid_payload', 400)
    request_hash = hashlib.sha256(json.dumps({'post_id': post_id, **payload}, sort_keys=True).encode()).hexdigest()
    operation_id = str(uuid4())
    with get_connection() as conn:
        _operation_lock(conn, payload['client_request_id'])
        previous = _existing_operation(conn, payload['client_request_id'], request_hash)
        if previous:
            if previous.get('pending'):
                raise ApiError('publish_in_progress', 409)
            return jsonify({**previous, 'already_applied': True})
        post = read_post(conn, post_id, lock=True)
        if version(post) != payload['expected_version']:
            raise ApiError('version_conflict', 409)
        if post['status'] not in {'Draft', 'Scheduled', 'Failed'}:
            raise ApiError('post_not_publishable', 409)
        from .services.platform_publishers import is_platform_publishable
        if not is_platform_publishable(post['platform']):
            raise ApiError('platform_publish_not_implemented', 409)
        conn.execute("UPDATE posts SET status='Publishing', updated_at=CURRENT_TIMESTAMP WHERE id=?", (post_id,))
        response = {'ok': False, 'pending': True, 'operation_id': operation_id, 'post_id': post_id}
        conn.execute('''INSERT INTO agent_operations
            (operation_id, agent_id, client_request_id, request_hash, post_id, reason, response_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (operation_id, g.agent_id, payload['client_request_id'], request_hash, post_id,
             payload['reason'].strip(), json.dumps(response)))
        conn.execute('INSERT INTO logs (post_id, level, message) VALUES (?, ?, ?)',
                     (post_id, 'INFO', f'Agent requested publication ({operation_id}): {payload["reason"].strip()}'))
    result = publish_post_now(post_id)
    with get_connection() as conn:
        final_post = serialize(conn, read_post(conn, post_id))
        response = {'ok': result['ok'], 'operation_id': operation_id, 'post_id': post_id,
                    'message': result.get('message', ''), 'post': final_post, 'already_applied': False}
        conn.execute('UPDATE agent_operations SET response_json=? WHERE operation_id=?',
                     (json.dumps(response), operation_id))
    return jsonify(**response), (200 if result['ok'] else 502)


@bp.delete('/rss/articles/<int:article_id>')
def delete_agent_rss_article(article_id):
    _require_manage()
    payload = request.get_json(silent=True)
    required = {'expected_title', 'expected_url', 'reason'}
    if (not isinstance(payload, dict) or set(payload) != required
            or any(not isinstance(payload[key], str) for key in required)
            or not 1 <= len(payload['expected_title'].strip()) <= 500
            or not 1 <= len(payload['expected_url'].strip()) <= 2048
            or not 1 <= len(payload['reason'].strip()) <= 1000):
        raise ApiError('invalid_payload', 400)
    with get_connection() as conn:
        article = conn.execute('SELECT id, title, url FROM rss_items WHERE id = ?', (article_id,)).fetchone()
        if article is None:
            raise ApiError('article_not_found', 404)
        if article['title'] != payload['expected_title'] or article['url'] != payload['expected_url']:
            raise ApiError('article_version_conflict', 409)
        post_count = conn.execute('SELECT COUNT(*) AS count FROM posts WHERE rss_item_id = ?', (article_id,)).fetchone()['count']
    delete_rss_group(article_id)
    add_log(None, 'INFO',
            f'Agent {g.agent_id} deleted RSS article #{article_id}: {payload["reason"].strip()}')
    return jsonify(ok=True, article_id=article_id, deleted=True, deleted_posts=post_count)


@bp.get('/dashboard')
def dashboard():
    with get_connection() as conn:
        counts = {row['status'].lower(): row['count'] for row in conn.execute(
            'SELECT status, COUNT(*) AS count FROM posts GROUP BY status').fetchall()}
    occurrences = list_scheduled_occurrences()
    return jsonify(draft=counts.get('draft', 0), scheduled_posts=counts.get('scheduled', 0),
                   scheduled_occurrences=len(occurrences),
                   posts_with_pending_occurrences=len({row['post_id'] for row in occurrences}),
                   published=counts.get('published', 0), failed=counts.get('failed', 0),
                   updated_at=app_now().isoformat())


@bp.get('/scheduled/occurrences')
def scheduled_occurrences():
    rows = list_scheduled_occurrences()
    for row in rows:
        row['occurrence_id'] = f"schedule:{row['schedule_id']}" if row['schedule_id'] else f"post:{row['post_id']}:primary"
    return jsonify(occurrences=rows, total=len(rows))


@bp.get('/scheduled/posts')
def scheduled_posts():
    ids = sorted({row['post_id'] for row in list_scheduled_occurrences()})
    with get_connection() as conn:
        return jsonify(posts=[serialize(conn, read_post(conn, post_id)) for post_id in ids], total=len(ids))
