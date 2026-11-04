"""The Flask application factory."""

from __future__ import annotations

from dataclasses import dataclass

from flask import Flask, render_template
from sqlalchemy.pool import NullPool

from .assistant import SupportAssistant
from .config import Settings
from .extensions import db

# No script, style or image comes from anywhere but this site: the first version loaded Bootstrap and jQuery
# from CDNs and had inline scripts and styles in every page.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


@dataclass(slots=True)
class Services:
    settings: Settings
    assistant: SupportAssistant


def create_app(
    settings: Settings | None = None,
    assistant: SupportAssistant | None = None,
    create_tables: bool = True,
) -> Flask:
    """`settings` default to the environment; tests pass settings and an `assistant` on a fake OpenAI."""
    settings = settings or Settings.from_env()
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=settings.secret_key,
        SQLALCHEMY_DATABASE_URI=settings.database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # A SQLite file is opened and closed per request: no pool that keeps file handles open
        SQLALCHEMY_ENGINE_OPTIONS=(
            {"poolclass": NullPool} if settings.database_url.startswith("sqlite") else {}
        ),
        SESSION_COOKIE_SECURE=settings.cookie_secure,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=64 * 1024,  # a chat message or a sign-up form is far smaller than this
    )
    app.extensions["lilac"] = Services(settings=settings, assistant=assistant or SupportAssistant(settings))

    db.init_app(app)

    from .views import bp

    app.register_blueprint(bp)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Frame-Options", "DENY")
        # Pages hold a customer's name, email and conversation
        if not response.headers.get("Cache-Control"):
            response.headers["Cache-Control"] = "no-store"
        return response

    for code, title in (
        (400, "Bad request"),
        (401, "Sign in required"),
        (403, "Not allowed"),
        (404, "Not found"),
        (405, "Method not allowed"),
        (413, "Too large"),
    ):

        def handler(error, code=code, title=title):
            message = getattr(error, "description", "") or title
            return render_template("error.html", code=code, title=title, message=message), code

        app.register_error_handler(code, handler)

    if create_tables:
        with app.app_context():
            db.create_all()
    return app
