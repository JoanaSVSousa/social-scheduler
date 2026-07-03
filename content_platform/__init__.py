from pathlib import Path
import os
from secrets import token_urlsafe

from flask import Flask, redirect, request, url_for

from .auth import is_logged_in, should_require_login
from .database import DEFAULT_DB_PATH, init_db
from .routes import bp
from .security import add_security_headers, csrf_token


def create_app():
    project_root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        instance_relative_config=False,
        template_folder=str(project_root / "templates"),
        static_folder=str(project_root / "static"),
    )
    app.config["DATABASE"] = str(DEFAULT_DB_PATH)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", token_urlsafe(32))
    app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("SESSION_COOKIE_SECURE", "1") == "1"

    init_db(app.config["DATABASE"])
    app.context_processor(lambda: {"csrf_token": csrf_token})
    app.after_request(add_security_headers)

    @app.before_request
    def require_app_login():
        if should_require_login(request.endpoint) and not is_logged_in():
            return redirect(url_for("main.login", next=request.path))

    app.register_blueprint(bp)

    return app
