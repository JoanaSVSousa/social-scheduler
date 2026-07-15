from functools import wraps
import os

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


DEFAULT_ADMIN_PASSWORD = "change-me-local-admin"
DEFAULT_ADMIN_USERNAME = "SquaredRedes"
DEFAULT_EDITOR_USERNAME = "squaredp"

ADMIN_ONLY_ENDPOINTS = {
    "main.social_account_settings",
    "main.save_social_account_settings",
    "main.verify_social_account_settings",
    "main.connect_facebook_account",
    "main.meta_oauth_callback",
    "main.facebook_oauth_callback",
    "main.extend_facebook_page_token",
    "main.connect_threads_account",
    "main.threads_oauth_callback",
    "main.delete_social_account_settings",
    "main.rss_articles",
    "main.rss_feeds",
    "main.check_rss",
    "main.seed_squared_rss",
    "main.edit_rss_feed",
    "main.remove_rss_feed",
}


def admin_password_hash():
    configured_hash = os.environ.get("ADMIN_PASSWORD_HASH")
    if configured_hash:
        return configured_hash
    password = os.environ.get("ADMIN_PASSWORD", DEFAULT_ADMIN_PASSWORD)
    return generate_password_hash(password)


def verify_admin_password(password):
    return check_password_hash(admin_password_hash(), password)


def verify_admin_credentials(username, password):
    expected_username = os.environ.get("ADMIN_USERNAME", DEFAULT_ADMIN_USERNAME)
    return username == expected_username and verify_admin_password(password)


def editor_password_hash():
    configured_hash = os.environ.get("EDITOR_PASSWORD_HASH")
    if configured_hash:
        return configured_hash
    password = os.environ.get("EDITOR_PASSWORD")
    return generate_password_hash(password) if password else ""


def verify_editor_password(password):
    configured_hash = editor_password_hash()
    return bool(configured_hash) and check_password_hash(configured_hash, password)


def verify_user_credentials(username, password):
    if verify_admin_credentials(username, password):
        return "admin"

    expected_username = os.environ.get("EDITOR_USERNAME", DEFAULT_EDITOR_USERNAME)
    if username == expected_username and verify_editor_password(password):
        return "editor"

    return ""


def is_logged_in():
    return session.get("admin_authenticated") is True


def current_user_role():
    if not is_logged_in():
        return ""
    return session.get("user_role") or "admin"


def is_admin():
    return current_user_role() == "admin"


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def should_require_login(endpoint):
    if endpoint in {None, "healthz", "main.login", "static"}:
        return False
    return True


def should_require_admin(endpoint):
    if endpoint in ADMIN_ONLY_ENDPOINTS:
        return True
    if not endpoint or not endpoint.startswith("main."):
        return False
    endpoint_name = endpoint.removeprefix("main.")
    return (
        "rss" in endpoint_name
        or "social_account" in endpoint_name
        or "facebook" in endpoint_name
        or "instagram" in endpoint_name
        or "threads" in endpoint_name
    )
