import unittest
from unittest.mock import patch
from urllib.request import Request

from content_platform.services import platform_publishers


class SocialAccountVerificationTests(unittest.TestCase):
    def test_x_oauth1_verification_reads_profile_and_matches_handle(self):
        account = {
            "account_handle": "@squared_potato",
            "auth_type": "oauth1",
            "credentials": {
                "api_key": "consumer-key",
                "api_secret": "consumer-secret",
                "access_token": "user-token",
                "access_token_secret": "user-secret",
            },
        }

        with patch.object(platform_publishers, "_x_oauth1_header", return_value="OAuth signed") as sign, \
             patch.object(platform_publishers, "_request_json", return_value={
                 "data": {"id": "123", "username": "squared_potato"}
             }) as request_json:
            message = platform_publishers.verify_x_account(account)

        sign.assert_called_once_with("GET", "https://api.x.com/2/users/me", account["credentials"])
        request = request_json.call_args.args[0]
        self.assertIsInstance(request, Request)
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "OAuth signed")
        self.assertIn("read-only", message.lower())

    def test_x_oauth2_verification_uses_user_token_and_rejects_wrong_account(self):
        account = {
            "account_handle": "@squared_potato",
            "auth_type": "oauth2",
            "credentials": {"oauth2_user_token": "user-context-token"},
        }
        with patch.object(platform_publishers, "_request_json", return_value={
            "data": {"id": "123", "username": "other_account"}
        }) as request_json:
            with self.assertRaisesRegex(RuntimeError, "belongs to @other_account"):
                platform_publishers.verify_x_account(account)

        request = request_json.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer user-context-token")

    def test_bluesky_verification_authenticates_but_does_not_publish(self):
        account = {
            "account_handle": "@squaredpotato",
            "auth_type": "app_password",
            "credentials": {
                "identifier": "squaredpotato.bsky.social",
                "app_password": "app-password",
                "pds_url": "https://bsky.social",
            },
        }
        with patch.object(platform_publishers, "_post_json", return_value={
            "handle": "squaredpotato.bsky.social",
            "did": "did:plc:abc123",
            "accessJwt": "ephemeral-jwt",
            "refreshJwt": "ephemeral-refresh",
        }) as create_session:
            message = platform_publishers.verify_bluesky_account(account)

        create_session.assert_called_once_with(
            "https://bsky.social/xrpc/com.atproto.server.createSession",
            {"identifier": "squaredpotato.bsky.social", "password": "app-password"},
            endpoint_name="account verification",
            error_label="Bluesky API",
        )
        self.assertIn("No post was created", message)

    def test_bluesky_verification_rejects_a_different_authenticated_handle(self):
        account = {
            "account_handle": "@squaredpotato",
            "credentials": {
                "identifier": "squaredpotato.bsky.social",
                "app_password": "app-password",
                "pds_url": "https://bsky.social",
            },
        }
        with patch.object(platform_publishers, "_post_json", return_value={
            "handle": "someone-else.bsky.social",
            "did": "did:plc:abc123",
            "accessJwt": "ephemeral-jwt",
        }):
            with self.assertRaisesRegex(RuntimeError, "belongs to @someone-else.bsky.social"):
                platform_publishers.verify_bluesky_account(account)


if __name__ == "__main__":
    unittest.main()
