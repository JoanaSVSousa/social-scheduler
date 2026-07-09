import base64
import hashlib
import json
import os
from datetime import datetime

from flask import current_app

from ..database import get_connection


PUBLIC_FIELDS = ["account_label", "account_handle", "auth_type"]
STATUS_CONNECTED = "Connected"
STATUS_NEEDS_VERIFICATION = "Needs verification"

SOCIAL_ACCOUNT_SCHEMAS = {
    "Instagram": {
        "description": "Meta/Instagram publishing usually needs a professional IG account, a linked Facebook Page, and a long-lived access token.",
        "auth_options": [("meta_graph", "Meta Graph API")],
        "fields": [
            {"name": "instagram_business_id", "label": "Instagram Business ID", "placeholder": "1784...", "example": "Example: 17841400000000000"},
            {"name": "facebook_page_id", "label": "Linked Facebook Page ID", "placeholder": "Page ID", "example": "Example: 123456789012345"},
            {"name": "access_token", "label": "Long-lived Access Token", "placeholder": "Paste Meta access token", "example": "Starts with EAA..."},
        ],
    },
    "Facebook": {
        "description": "Facebook Page publishing needs the Page ID and a Page access token with publishing permissions.",
        "auth_options": [("meta_graph", "Meta Graph API")],
        "fields": [
            {"name": "page_id", "label": "Page ID", "placeholder": "Facebook Page ID", "example": "Example: 123456789012345"},
            {"name": "access_token", "label": "Page Access Token", "placeholder": "Paste Page access token", "example": "Starts with EAA..."},
            {"name": "app_id", "label": "App ID", "placeholder": "Optional Meta App ID", "example": "Numeric Meta app id"},
            {"name": "app_secret", "label": "App Secret", "placeholder": "Optional Meta App Secret", "example": "Meta app secret string"},
        ],
    },
    "LinkedIn": {
        "description": "LinkedIn publishing needs OAuth credentials and, for company posts, the organization ID/URN.",
        "auth_options": [("oauth", "LinkedIn OAuth")],
        "fields": [
            {"name": "organization_id", "label": "Organization ID / URN", "placeholder": "urn:li:organization:...", "example": "Example: urn:li:organization:123456"},
            {"name": "access_token", "label": "Access Token", "placeholder": "Paste LinkedIn access token", "example": "OAuth access token"},
            {"name": "refresh_token", "label": "Refresh Token", "placeholder": "Optional refresh token", "example": "OAuth refresh token, if issued"},
        ],
    },
    "X": {
        "description": "X posting uses user-context auth. For this MVP, OAuth 1.0a is recommended. Do not paste OAuth2 Client ID/Client Secret into the API Key/API Secret fields.",
        "auth_options": [("oauth1", "OAuth 1.0a user tokens"), ("oauth2", "OAuth 2.0")],
        "fields": [
            {"name": "api_key", "label": "API Key / Consumer Key", "placeholder": "OAuth1 API Key, not Client ID", "example": "Required for OAuth1. X Developer Portal > Keys and tokens > Consumer Keys > API Key.", "auth_types": ["oauth1"]},
            {"name": "api_secret", "label": "API Key Secret", "placeholder": "OAuth1 API Key Secret, not Client Secret", "example": "Required for OAuth1. X Developer Portal > Keys and tokens > Consumer Keys > API Key Secret.", "auth_types": ["oauth1"]},
            {"name": "access_token", "label": "OAuth1 Access Token", "placeholder": "OAuth1 user access token", "example": "Required for OAuth1. X Developer Portal > Authentication Tokens > Access Token.", "auth_types": ["oauth1"]},
            {"name": "access_token_secret", "label": "Access Token Secret", "placeholder": "OAuth1 user access token secret", "example": "Required for OAuth1. X Developer Portal > Authentication Tokens > Access Token Secret.", "auth_types": ["oauth1"]},
            {"name": "oauth2_user_token", "label": "OAuth2 User Access Token", "placeholder": "OAuth2 user-context token", "example": "Must be user-context with tweet.write, not application-only bearer.", "auth_types": ["oauth2"]},
            {"name": "bearer_token", "label": "Fallback Bearer Token", "placeholder": "Optional OAuth2 user bearer token", "example": "Do not use the app-only Bearer Token here; it cannot create posts.", "auth_types": ["oauth2"]},
        ],
    },
    "Threads": {
        "description": "Threads publishing uses Meta/Threads credentials: a Threads user ID and access token.",
        "auth_options": [("threads_api", "Threads API")],
        "fields": [
            {"name": "threads_user_id", "label": "Threads User ID", "placeholder": "Threads user ID", "example": "Numeric Threads user id"},
            {"name": "access_token", "label": "Access Token", "placeholder": "Paste Threads access token", "example": "Threads/Meta access token"},
        ],
    },
    "Bluesky": {
        "description": "Bluesky is the lightest first integration: use the account handle/email and an app password, not your main password. Leave PDS URL as https://bsky.social unless you use a custom PDS; do not paste a bsky.app profile URL.",
        "auth_options": [("app_password", "Handle + app password")],
        "fields": [
            {"name": "identifier", "label": "Handle or Email", "placeholder": "squaredpotato.bsky.social", "example": "Example: squaredpotato.bsky.social"},
            {"name": "app_password", "label": "App Password", "placeholder": "Paste Bluesky app password", "example": "Generated in Bluesky settings, not your main password"},
            {"name": "pds_url", "label": "PDS URL", "placeholder": "https://bsky.social", "example": "Use https://bsky.social, not bsky.app"},
        ],
    },
    "YouTube Shorts": {
        "description": "YouTube uploads use Google OAuth. A refresh token is normally needed for scheduled publishing.",
        "auth_options": [("google_oauth", "Google OAuth")],
        "fields": [
            {"name": "channel_id", "label": "Channel ID", "placeholder": "YouTube channel ID", "example": "Example: UCxxxxxxxxxxxxxxxx"},
            {"name": "client_id", "label": "OAuth Client ID", "placeholder": "Google OAuth client ID", "example": "Ends with .apps.googleusercontent.com"},
            {"name": "client_secret", "label": "OAuth Client Secret", "placeholder": "Google OAuth client secret", "example": "From Google Cloud OAuth client"},
            {"name": "refresh_token", "label": "Refresh Token", "placeholder": "Google refresh token", "example": "Long token returned by OAuth consent"},
        ],
    },
    "TikTok": {
        "description": "TikTok publishing uses a developer app plus access tokens for the connected creator account.",
        "auth_options": [("tiktok_api", "TikTok API")],
        "fields": [
            {"name": "client_key", "label": "Client Key", "placeholder": "TikTok client key", "example": "From TikTok developer app"},
            {"name": "client_secret", "label": "Client Secret", "placeholder": "TikTok client secret", "example": "From TikTok developer app"},
            {"name": "access_token", "label": "Access Token", "placeholder": "TikTok access token", "example": "Connected creator access token"},
            {"name": "open_id", "label": "Open ID", "placeholder": "Connected account open_id", "example": "User open_id returned by TikTok OAuth"},
        ],
    },
}

DEFAULT_SOCIAL_ACCOUNT_SCHEMA = {
    "description": "Store the credentials required by this platform.",
    "auth_options": [("api_keys", "API keys / tokens")],
    "fields": [
        {"name": "api_key", "label": "API Key", "placeholder": "Paste API key", "example": "API key from developer dashboard"},
        {"name": "api_secret", "label": "API Secret", "placeholder": "Paste API secret", "example": "API secret from developer dashboard"},
        {"name": "access_token", "label": "Access Token", "placeholder": "Paste access token", "example": "OAuth access token"},
    ],
}


def list_social_accounts():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM social_accounts ORDER BY platform ASC").fetchall()
    return rows


def social_accounts_by_platform():
    return {account["platform"]: account for account in list_social_accounts()}


def get_social_account(platform):
    with get_connection() as conn:
        return conn.execute("SELECT * FROM social_accounts WHERE platform = ?", (platform,)).fetchone()


def save_social_account(platform, account_label, account_handle, auth_type, credential_values):
    existing = get_social_account(platform)
    credentials = _stored_credentials(existing, fail_closed=True)
    for field_name in credential_field_names(platform):
        value = _normalize_credential_value(platform, field_name, credential_values.get(field_name, ""))
        if value:
            credentials[field_name] = value

    encrypted_credentials = encrypt_credentials(credentials)
    verified_at = datetime.now().strftime("%Y-%m-%dT%H:%M")
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO social_accounts (
                platform, account_label, account_handle, auth_type, encrypted_credentials,
                connection_status, last_verified_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform) DO UPDATE SET
                account_label = excluded.account_label,
                account_handle = excluded.account_handle,
                auth_type = excluded.auth_type,
                encrypted_credentials = excluded.encrypted_credentials,
                connection_status = excluded.connection_status,
                last_verified_at = excluded.last_verified_at,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                platform,
                account_label,
                account_handle,
                auth_type,
                encrypted_credentials,
                STATUS_NEEDS_VERIFICATION,
                verified_at,
            ),
        )


def delete_social_account(platform):
    with get_connection() as conn:
        conn.execute("DELETE FROM social_accounts WHERE platform = ?", (platform,))


def credential_summary(account):
    credentials = _stored_credentials(account)
    return {field: bool(credentials.get(field)) for field in credential_field_names(account["platform"])}


def credential_schema_for_platform(platform):
    return SOCIAL_ACCOUNT_SCHEMAS.get(platform, DEFAULT_SOCIAL_ACCOUNT_SCHEMA)


def credential_field_names(platform):
    return [field["name"] for field in credential_schema_for_platform(platform)["fields"]]


def _normalize_credential_value(platform, field_name, value):
    value = (value or "").strip()
    if platform == "Bluesky" and field_name == "pds_url":
        normalized = value.lower().rstrip("/")
        if normalized in {"", "bsky.app", "www.bsky.app", "https://bsky.app", "https://www.bsky.app"}:
            return "https://bsky.social"
    return value


def decrypt_credentials_for_publisher(platform):
    account = get_social_account(platform)
    if not account:
        return None
    credentials = _stored_credentials(account, fail_closed=True)
    return {
        "platform": account["platform"],
        "account_label": account["account_label"],
        "account_handle": account["account_handle"],
        "auth_type": account["auth_type"],
        "credentials": credentials,
    }


def encrypt_credentials(credentials):
    fernet = _fernet()
    payload = json.dumps(credentials, sort_keys=True).encode("utf-8")
    return fernet.encrypt(payload).decode("utf-8")


def decrypt_credentials(encrypted_credentials):
    if not encrypted_credentials:
        return {}
    fernet = _fernet()
    payload = fernet.decrypt(encrypted_credentials.encode("utf-8"))
    return json.loads(payload.decode("utf-8"))


def _stored_credentials(account, fail_closed=False):
    if not account:
        return {}
    try:
        return decrypt_credentials(account["encrypted_credentials"])
    except Exception as exc:
        if fail_closed:
            raise RuntimeError(
                "Stored social credentials could not be decrypted. Check CREDENTIALS_ENCRYPTION_KEY before saving again."
            ) from exc
        return {}


def _fernet():
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:
        raise RuntimeError("Install cryptography to store social account credentials securely.") from exc

    return Fernet(_encryption_key())


def _encryption_key():
    configured_key = os.environ.get("CREDENTIALS_ENCRYPTION_KEY", "").strip()
    if configured_key:
        return configured_key.encode("utf-8")

    secret_key = current_app.config.get("SECRET_KEY") or os.environ.get("SECRET_KEY", "")
    digest = hashlib.sha256(secret_key.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)
