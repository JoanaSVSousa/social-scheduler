from functools import wraps
import os

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


DEFAULT_ADMIN_PASSWORD = "change-me-local-admin"
DEFAULT_ADMIN_USERNAME = "SquaredRedes"


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


def is_logged_in():
    return session.get("admin_authenticated") is True


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if not is_logged_in():
            return redirect(url_for("main.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped_view


def should_require_login(endpoint):
    if endpoint in {None, "main.login", "static"}:
        return False
    return True
