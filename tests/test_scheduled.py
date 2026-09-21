import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from content_platform import create_app
from content_platform.database import get_connection


class ScheduledTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path = Path(self.temp.name) / 'test.db'
        for target, value in [('content_platform.DEFAULT_DB_PATH', path),
                              ('content_platform.database.DEFAULT_DB_PATH', path)]:
            patcher = patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'DATABASE_URL': '', 'APP_TIMEZONE': 'Europe/Lisbon'})
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
            session['user_role'] = 'editor'

    def post(self, title, status='Scheduled', date='2026-09-22T10:00'):
        with get_connection() as conn:
            return conn.execute('INSERT INTO posts (title, content, platform, status, scheduled_at) VALUES (?, ?, ?, ?, ?)',
                                (title, '<script>unsafe</script>', 'Facebook', status, date)).lastrowid

    def occurrence(self, post_id, date, status):
        with get_connection() as conn:
            conn.execute('INSERT INTO post_schedules (post_id, scheduled_at, status) VALUES (?, ?, ?)', (post_id, date, status))

    def rows(self):
        response = self.client.get('/api/scheduled')
        self.assertEqual(response.status_code, 200)
        return response.json['posts']

    def test_page_and_empty(self):
        response = self.client.get('/scheduled')
        self.assertEqual(response.status_code, 200)
        self.assertIn('A carregar', response.text)
        self.assertNotIn('Não existem posts agendados', response.text)
        for action in ['Publish now', 'Delete', 'Retry', 'Upload', 'New Post']:
            self.assertNotIn(action, response.text)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.client.get('/nonexistent-route').status_code, 404)

    def test_states_order_and_timezone(self):
        self.post('late')
        self.post('draft', 'Draft')
        self.post('published', 'Published')
        self.post('failed', 'Failed')
        self.post('winter', date='2026-01-22T10:00')
        rows = self.rows()
        self.assertEqual([row['title'] for row in rows], ['winter', 'late'])
        self.assertTrue(rows[0]['scheduled_at'].endswith('+00:00'))
        self.assertTrue(rows[1]['scheduled_at'].endswith('+01:00'))
        self.assertEqual(rows[0]['timezone'], 'Europe/Lisbon')

    def test_occurrences_authoritative_with_distinct_post_status(self):
        post_id = self.post('recycled', 'Published')
        self.occurrence(post_id, '2026-09-22T10:00', 'Published')
        self.occurrence(post_id, '2026-09-23T10:00', 'Failed')
        self.occurrence(post_id, '2026-09-24T10:00', 'Scheduled')
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['status'], 'Scheduled')
        self.assertEqual(rows[0]['post_status'], 'Published')
        self.assertIn('2026-09-24', rows[0]['scheduled_at'])
        other = self.post('completed occurrences')
        self.occurrence(other, '2026-09-22T10:00', 'Published')
        self.assertEqual(len(self.rows()), 1)

    def test_media_source_errors_and_no_writes(self):
        post_id = self.post('details')
        with get_connection() as conn:
            feed = conn.execute("INSERT INTO rss_feeds (name, url, target_platforms) VALUES ('test', 'https://example.test/feed', 'Facebook')").lastrowid
            item = conn.execute("INSERT INTO rss_items (feed_id, item_guid, title, url) VALUES (?, 'test', 'source', 'https://example.test/article')", (feed,)).lastrowid
            conn.execute('UPDATE posts SET rss_item_id = ? WHERE id = ?', (item, post_id))
            conn.execute("INSERT INTO media_assets (post_id, filename, original_filename, media_type) VALUES (?, 'a.png', 'photo.png', 'image')", (post_id,))
            conn.execute("INSERT INTO logs (post_id, level, message) VALUES (?, 'ERROR', 'test error')", (post_id,))
            before = '\n'.join(conn.raw_connection.iterdump())
        self.client.get('/scheduled')
        row = self.rows()[0]
        self.assertEqual(row['url'], 'https://example.test/article')
        self.assertEqual(row['media'][0]['name'], 'photo.png')
        self.assertEqual(row['error'], 'test error')
        with get_connection() as conn:
            self.assertEqual(before, '\n'.join(conn.raw_connection.iterdump()))

    def test_failure_not_empty(self):
        with patch('content_platform.routes.list_scheduled_occurrences', side_effect=RuntimeError('synthetic')):
            with self.assertLogs(self.app.logger, level='ERROR'):
                response = self.client.get('/api/scheduled')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('posts', response.json)
        self.assertNotIn('synthetic', response.text)

    def test_access_and_get_only(self):
        for path in ['/scheduled', '/api/scheduled']:
            self.assertEqual(self.client.post(path).status_code, 405)
        with self.client.session_transaction() as session:
            session.clear()
        for path in ['/scheduled', '/api/scheduled']:
            self.assertEqual(self.client.get(path).status_code, 302)

    def test_invalid_date_visible(self):
        self.post('invalid', date='bad-date')
        row = self.rows()[0]
        self.assertIsNone(row['scheduled_at'])
        self.assertTrue(row['date_error'])


if __name__ == '__main__':
    unittest.main()
