from secrets import token_urlsafe

from flask import abort, request, session


def csrf_token():
    token = session.get("csrf_token")
    if token is None:
        token = token_urlsafe(32)
        session["csrf_token"] = token
    return token


def validate_csrf():
    token = session.get("csrf_token")
    submitted_token = request.form.get("csrf_token")
    if not token or not submitted_token or submitted_token != token:
        abort(400)


def add_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.is_secure or request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https://squared-potato.pt https://www.squared-potato.pt; "
        "media-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )
    return response
