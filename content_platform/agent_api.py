"""Versioned, narrowly scoped agent access; browser sessions confer no API access."""
import hashlib
import hmac
import json
import os
from uuid import uuid4

from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .database import get_connection
from .services.clock import app_now
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
    matched = False
    for variable, writable in [('SUPERNOVA_AGENT_READ_TOKEN_SHA256', False),
                                ('SUPERNOVA_AGENT_CLASSIFY_TOKEN_SHA256', True)]:
        configured = os.environ.get(variable, '')
        if len(configured) == 64 and hmac.compare_digest(digest, configured):
            matched = True
            g.can_classify = g.can_classify or writable
    if not matched:
        raise ApiError('unauthorized', 401)
    # Stable audit identity without storing a usable credential.
    g.agent_id = 'agent-' + digest[:16]
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and not g.can_classify:
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
                   capabilities=['read_posts', 'read_scheduled', 'classify_posts'] if g.can_classify
                   else ['read_posts', 'read_scheduled'])


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
