import base64
import hashlib
import json
import os
from datetime import datetime

from flask import current_app

from ..database import get_connection


SECRET_FIELDS = ["api_key", "api_secret", "access_token", "refresh_token", "page_id"]
PUBLIC_FIELDS = ["account_label", "account_handle", "auth_type"]
STATUS_CONNECTED = "Connected"
STATUS_NEEDS_VERIFICATION = "Needs verification"


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
    for field_name in SECRET_FIELDS:
        value = credential_values.get(field_name, "").strip()
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
    return {field: bool(credentials.get(field)) for field in SECRET_FIELDS}


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
