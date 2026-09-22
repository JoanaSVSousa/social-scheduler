"""Opt-in integration tests against a disposable LOCAL supernova_test database only."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from content_platform import create_app
from content_platform.database import DatabaseConnection, get_connection, init_db, insert_and_get_id


@unittest.skipUnless(os.environ.get('SUPERNOVA_TEST_POSTGRES_URL'), 'Local Postgres test URL not configured')
class PostgresAgentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ['SUPERNOVA_TEST_POSTGRES_URL']
        parsed = urlsplit(url)
        if parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.path != '/supernova_test' or parsed.query:
            raise RuntimeError('Refusing non-local or non-test database')
        cls.env = patch.dict(os.environ, {
            'DATABASE_URL': url,
            'SUPERNOVA_AGENT_CLASSIFY_TOKEN_SHA256': hashlib.sha256(b'postgres-test-only').hexdigest(),
        })
        cls.env.start()
        cls.addClassCleanup(cls.env.stop)
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.headers = {'Authorization': 'Bearer postgres-test-only'}

    def setUp(self):
        with get_connection() as conn:
            conn.execute('TRUNCATE agent_operations, logs, post_schedules, media_assets, rss_items, rss_feeds, posts RESTART IDENTITY CASCADE')
            self.post_id = insert_and_get_id(conn,
                'INSERT INTO posts (title, content, platform, status) VALUES (?, ?, ?, ?)',
                ('Synthetic post', 'Original copy', 'Facebook', 'Draft'))
        self.client = self.app.test_client()

    def get_post(self):
        response = self.client.get(f'/api/posts/{self.post_id}', headers=self.headers)
        self.assertEqual(response.status_code, 200)
        return response.json['post']

    def payload(self):
        return {'classification': 'news', 'reason': 'Synthetic integration test',
                'expected_version': self.get_post()['version'], 'client_request_id': 'pg-request'}

    def change(self, body):
        return self.app.test_client().patch(f'/api/posts/{self.post_id}/classification', json=body, headers=self.headers)

    def test_migration_repeat_and_read_endpoints(self):
        init_db()
        init_db()
        with get_connection() as conn:
            self.assertTrue(conn.execute("SELECT relrowsecurity FROM pg_class WHERE oid = 'agent_operations'::regclass").fetchone()['relrowsecurity'])
        for path in ['/api/version', '/api/posts?status=draft', f'/api/posts/{self.post_id}/verify',
                     '/api/dashboard', '/api/scheduled/posts', '/api/scheduled/occurrences']:
            self.assertEqual(self.client.get(path, headers=self.headers).status_code, 200, path)
        self.assertEqual(self.client.get('/api/posts').status_code, 401)
        self.assertEqual(self.get_post()['classification'], 'all_green')

    def test_concurrent_retry_and_optimistic_conflict(self):
        body = self.payload()
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(self.change, [body, body]))
        self.assertEqual([r.status_code for r in responses], [200, 200])
        self.assertEqual(responses[0].json['operation_id'], responses[1].json['operation_id'])
        self.assertEqual(sorted(r.json['already_applied'] for r in responses), [False, True])
        self.assertEqual(self.change({**body, 'client_request_id': 'new-request'}).status_code, 409)
        self.assertEqual(self.change({**body, 'reason': 'changed request'}).status_code, 409)
        self.assertEqual(self.get_post()['copy'], 'Original copy')
        self.assertEqual(self.get_post()['classification'], 'news')
        with get_connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM agent_operations').fetchone()['n'], 1)

    def test_concurrent_distinct_operations_only_one_wins(self):
        body = self.payload()
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(self.change, [body, {**body, 'client_request_id': 'different'}]))
        self.assertEqual(sorted(r.status_code for r in responses), [200, 409])

    def test_audit_failure_rolls_back_classification(self):
        body = self.payload()
        original = DatabaseConnection.execute
        def fail_audit(conn, query, params=()):
            if 'INSERT INTO agent_operations' in query:
                raise RuntimeError('Synthetic audit failure')
            return original(conn, query, params)
        with patch.object(DatabaseConnection, 'execute', fail_audit):
            with self.assertLogs(self.app.logger, level='ERROR'):
                self.assertEqual(self.change(body).status_code, 503)
        self.assertEqual(self.get_post()['classification'], 'all_green')
        self.assertEqual(self.get_post()['version'], body['expected_version'])
