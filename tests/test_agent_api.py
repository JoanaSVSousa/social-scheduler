import hashlib
import os
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import unittest
import test_scheduled
from content_platform.database import get_connection


class AgentApiTests(unittest.TestCase):
    post = test_scheduled.ScheduledTests.post
    occurrence = test_scheduled.ScheduledTests.occurrence
    def setUp(self):
        test_scheduled.ScheduledTests.setUp(self)
        env = patch.dict(os.environ, {
            'SUPERNOVA_AGENT_READ_TOKEN_SHA256': hashlib.sha256(b'read-test').hexdigest(),
            'SUPERNOVA_AGENT_CLASSIFY_TOKEN_SHA256': hashlib.sha256(b'write-test').hexdigest(),
        })
        env.start()
        self.addCleanup(env.stop)
        self.headers = {'Authorization': 'Bearer write-test'}
        self.post_id = self.post('Agent test', 'Draft')

    def detail(self, post_id=None):
        return self.client.get(f'/api/posts/{post_id or self.post_id}', headers=self.headers).json['post']

    def payload(self, **changes):
        return dict(classification='news', reason='Synthetic test', expected_version=self.detail()['version'],
                    client_request_id='request-1', **changes)

    def change(self, body, client=None):
        return (client or self.client).patch(f'/api/posts/{self.post_id}/classification', json=body, headers=self.headers)

    def test_api_requires_own_token_even_with_browser_session(self):
        self.assertEqual(self.client.get('/api/posts').status_code, 401)
        self.assertEqual(self.client.get('/api/posts', headers={'Authorization': 'Bearer bad'}).status_code, 401)
        with patch.dict(os.environ, {'SUPERNOVA_AGENT_READ_TOKEN_SHA256': '', 'SUPERNOVA_AGENT_CLASSIFY_TOKEN_SHA256': ''}):
            self.assertEqual(self.client.get('/api/posts', headers=self.headers).status_code, 401)
        response = self.client.get('/api/posts', headers={'Authorization': 'Bearer read-test'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertEqual(self.client.patch(f'/api/posts/{self.post_id}/classification', json=self.payload(),
                         headers={'Authorization': 'Bearer read-test'}).status_code, 403)
        anonymous = self.app.test_client()
        self.assertEqual(anonymous.post(f'/posts/{self.post_id}/publish-now', headers=self.headers).status_code, 302)

    def test_listing_filters_links_pagination(self):
        with get_connection() as conn:
            feed = conn.execute("INSERT INTO rss_feeds (name,url,target_platforms) VALUES ('f','https://example.test/feed','Facebook')").lastrowid
            article = conn.execute("INSERT INTO rss_items (feed_id,item_guid,title,url) VALUES (?,'g','Article','https://example.test/noticias/test')", (feed,)).lastrowid
            conn.execute('UPDATE posts SET rss_item_id = ? WHERE id = ?', (article,self.post_id))
        self.post('Other', 'Published')
        response = self.client.get('/api/posts?status=draft&classification=all_green&per_page=1', headers=self.headers)
        self.assertEqual(response.json['total'], 1)
        post = response.json['posts'][0]
        self.assertEqual(post['article_id'], article)
        self.assertEqual(post['article_url'], 'https://example.test/noticias/test')
        self.assertEqual(self.client.get('/api/posts?page=2&per_page=1', headers=self.headers).json['posts'][0]['title'], 'Other')
        for query in ['status=bogus', 'classification=ambiguous', 'per_page=101', 'page=0', 'page=-1', 'article_id=x', 'unknown=yes']:
            self.assertEqual(self.client.get('/api/posts?' + query, headers=self.headers).status_code, 400)
        self.assertEqual(self.client.get('/api/posts/999999', headers=self.headers).status_code, 404)

    def test_change_is_limited_audited_and_retry_safe(self):
        before = self.detail()
        body = self.payload()
        response = self.change(body)
        self.assertEqual(response.status_code, 200)
        after = self.detail()
        for key in before.keys() - {'source_type', 'classification', 'version', 'updated_at'}:
            self.assertEqual(before[key], after[key], key)
        self.assertEqual(after['classification'], 'news')
        self.assertNotEqual(before['version'], after['version'])
        retry = self.change(body).json
        self.assertTrue(retry['already_applied'])
        self.assertEqual(retry['operation_id'], response.json['operation_id'])
        with get_connection() as conn:
            operations = conn.execute('SELECT * FROM agent_operations').fetchall()
            self.assertEqual(len(operations), 1)
            self.assertEqual(operations[0]['reason'], 'Synthetic test')
            self.assertEqual(len(conn.execute("SELECT * FROM logs WHERE message LIKE 'Agent classification%'").fetchall()), 1)
        self.assertEqual(self.change({**body, 'reason': 'different'}).status_code, 409)
        self.assertEqual(self.change({**body, 'client_request_id': 'other'}).status_code, 409)
        verify = self.client.get(f'/api/posts/{self.post_id}/verify', headers=self.headers).json['post']
        self.assertEqual(verify, after)

    def test_concurrent_duplicate_writes_apply_once(self):
        body = self.payload()
        def run(_):
            return self.change(body, self.app.test_client()).json
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(run, range(2)))
        self.assertEqual(results[0]['operation_id'], results[1]['operation_id'])
        self.assertEqual(sorted(result['already_applied'] for result in results), [False, True])

    def test_existing_writer_invalidates_revision_and_transaction_rolls_back(self):
        body = self.payload()
        with get_connection() as conn:
            conn.execute('UPDATE posts SET content = ? WHERE id = ?', ('Updated by UI', self.post_id))
        self.assertEqual(self.change(body).status_code, 409)
        from content_platform.database import DatabaseConnection
        original = DatabaseConnection.execute
        def fail_audit(conn, query, params=()):
            if 'INSERT INTO agent_operations' in query:
                raise RuntimeError('synthetic audit failure')
            return original(conn, query, params)
        fresh = self.payload()
        with patch.object(DatabaseConnection, 'execute', fail_audit):
            with self.assertLogs(self.app.logger, level='ERROR'):
                self.assertEqual(self.change(fresh).status_code, 503)
        self.assertEqual(self.detail()['classification'], 'all_green')

    def test_rejects_unrelated_fields_and_unsupported_classification(self):
        body = self.payload()
        for value in [None, [], {**body, 'copy': 'overwrite'}, {**body, 'classification': 'ambiguous'},
                      {**body, 'classification': 'unclassified'}, {**body, 'reason': ''},
                      {**body, 'expected_version': 4}, {**body, 'classification': []}]:
            self.assertEqual(self.change(value).status_code, 400)
        unchanged = self.change({**body, 'classification': 'all_green'}).json
        self.assertFalse(unchanged['changed'])
        self.assertEqual(unchanged['version'], body['expected_version'])

    def test_dashboard_and_occurrences_have_explicit_units(self):
        self.post('scheduled')
        recycled = self.post('recycled', 'Published')
        self.occurrence(recycled, '2026-09-22T10:00', 'Scheduled')
        self.occurrence(recycled, '2026-09-23T10:00', 'Scheduled')
        counts = self.client.get('/api/dashboard', headers=self.headers).json
        self.assertEqual(counts['scheduled_posts'], 1)
        self.assertEqual(counts['scheduled_occurrences'], 3)
        self.assertEqual(counts['posts_with_pending_occurrences'], 2)
        self.assertEqual(self.client.get('/api/scheduled/posts', headers=self.headers).json['total'], 2)
        rows = self.client.get('/api/scheduled/occurrences', headers=self.headers).json['occurrences']
        self.assertEqual(len({row['occurrence_id'] for row in rows}), 3)
        self.assertEqual(self.client.get('/api/version', headers=self.headers).json['api_version'], '1')

    def test_browsing_cannot_reclassify_rss(self):
        with get_connection() as conn:
            feed = conn.execute("INSERT INTO rss_feeds (name,url,target_platforms) VALUES ('f','https://example.test/feed','Facebook')").lastrowid
            article = conn.execute("INSERT INTO rss_items (feed_id,item_guid,title,url) VALUES (?,'g','Article','https://example.test/noticias/test')", (feed,)).lastrowid
            conn.execute('UPDATE posts SET rss_item_id = ? WHERE id = ?', (article, self.post_id))
            before = '\n'.join(conn.raw_connection.iterdump())
        for path in ['/posts', '/', '/dashboard']:
            self.assertEqual(self.client.get(path).status_code, 200)
        with get_connection() as conn:
            self.assertEqual(before, '\n'.join(conn.raw_connection.iterdump()))
