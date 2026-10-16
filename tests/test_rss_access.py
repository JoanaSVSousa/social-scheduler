import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from content_platform import create_app
from content_platform.database import get_connection


class RssAccessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'test.db'
        for target in ('content_platform.DEFAULT_DB_PATH',
                       'content_platform.database.DEFAULT_DB_PATH'):
            patcher = patch(target, path)
            patcher.start()
            self.addCleanup(patcher.stop)
        env = patch.dict(os.environ, {'DATABASE_URL': ''})
        env.start()
        self.addCleanup(env.stop)
        self.app = create_app()
        self.app.config['TESTING'] = True
        self.client = self.app.test_client()
        with get_connection() as conn:
            conn.execute("INSERT INTO rss_feeds (id, name, url, target_platforms) VALUES (1, 'Feed', 'https://example.test/feed', 'Facebook')")
            for item_id in (1, 2, 65):
                conn.execute("INSERT INTO rss_items (id, feed_id, item_guid, title, url) VALUES (?, 1, ?, 'Article', 'https://example.test/article')", (item_id, str(item_id)))
            conn.execute("INSERT INTO posts (title, content, platform, status, rss_item_id) VALUES ('Version', '<script>unsafe</script>', 'Facebook', 'Draft', 1)")

    def login(self, role):
        with self.client.session_transaction() as session:
            session['admin_authenticated'] = True
            session['user_role'] = role

    def test_editor_reads_without_database_changes(self):
        self.login('editor')
        with get_connection() as conn:
            before = '\n'.join(conn.raw_connection.iterdump())
        for item_id in (1, 2, 65):
            response = self.client.get(f'/rss/articles/{item_id}')
            self.assertEqual(response.status_code, 200)
            self.assertIn('Read-only article', response.text)
            self.assertNotIn('class="version-editor"', response.text)
            self.assertEqual(self.client.head(f'/rss/articles/{item_id}').status_code, 200)
        self.assertIn('&lt;script&gt;', self.client.get('/rss/articles/1').text)
        self.assertEqual(self.client.get('/rss/articles/999999').status_code, 404)
        self.assertEqual(self.client.get('/api/scheduled').status_code, 200)
        with get_connection() as conn:
            self.assertEqual(before, '\n'.join(conn.raw_connection.iterdump()))

    def test_editor_mutations_and_other_rss_pages_remain_forbidden(self):
        self.login('editor')
        for path in ('/rss/articles/1', '/rss/articles/1/delete', '/rss/articles/1/publish-now', '/rss/check'):
            self.assertEqual(self.client.post(path).status_code, 403)
        for path in ('/rss/articles', '/rss', '/rss/1/edit'):
            self.assertEqual(self.client.get(path).status_code, 403)

    def test_anonymous_and_bearer_only_require_browser_login(self):
        for path in ('/rss/articles/1', '/rss/articles/999999'):
            response = self.client.get(path, headers={'Authorization': 'Bearer example'})
            self.assertEqual(response.status_code, 302)
            self.assertIn('/login', response.location)

    def test_admin_keeps_editor_page(self):
        self.login('admin')
        response = self.client.get('/rss/articles/1')
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="version-editor"', response.text)
        self.assertEqual(self.client.get('/rss/articles/999999').status_code, 404)
