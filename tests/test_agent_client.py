import contextlib
import io
import json
import unittest
from unittest.mock import patch

from scripts import supernova_agent as client


class AgentClientTests(unittest.TestCase):
    def test_rejects_remote_cleartext_and_missing_token_before_network(self):
        with self.assertRaises(ValueError):
            client.request_json('http://example.test', 'secret', '/api/posts')
        with self.assertRaises(ValueError):
            client.request_json('https://example.test', '', '/api/posts')
        self.assertIsNone(client.NoRedirects().redirect_request(None, None, 302, '', {}, 'https://other.test'))

    def test_classification_uses_explicit_version_key_and_checks_readback(self):
        args = ['client', '--base-url', 'https://example.test', 'classify', '7',
                '--classification', 'news', '--reason', 'Test decision',
                '--expected-version', 'a' * 64, '--request-id', 'unique-key']
        for current, expected_exit in [('b' * 64, 0), ('c' * 64, 2)]:
            output = io.StringIO()
            with patch('sys.argv', args), patch.dict('os.environ', {'SUPERNOVA_AGENT_TOKEN': 'test-token'}), \
                 patch.object(client, 'request_json', side_effect=[{'version': 'b' * 64, 'classification': 'news'},
                     {'post': {'version': current, 'classification': 'news'}}]) as request, \
                 contextlib.redirect_stdout(output):
                self.assertEqual(client.main(), expected_exit)
            self.assertEqual(request.call_args_list[0].args[2], '/api/posts/7/classification')
            self.assertEqual(request.call_args_list[0].args[3]['client_request_id'], 'unique-key')
            self.assertEqual(request.call_args_list[0].args[3]['expected_version'], 'a' * 64)
            self.assertEqual(request.call_args_list[1].args[2], '/api/posts/7/verify')
            self.assertEqual(json.loads(output.getvalue())['verification_matches'], expected_exit == 0)
