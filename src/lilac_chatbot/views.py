"""Routes: sign-up, sign-in, profile and the chat."""

from __future__ import annotations

import hmac
import re
import secrets
from functools import wraps
from urllib.parse import urlsplit

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from .app import Services
from .assistant import AssistantError
from .extensions import db
from .models import ChatMessage, ChatThread, User

bp = Blueprint("web", __name__)

USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,40}$")
EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD, MAX_PASSWORD = 10, 128  # the upper bound keeps the password hash cheap to refuse to compute
NAME_MAX = 100
# Checked when the account does not exist, so that "no such account" takes as long as "wrong password"
_DUMMY_HASH = generate_password_hash("not-a-real-password")


def services() -> Services:
    return current_app.extensions["lilac"]


# -- sessions and CSRF
def current_user() -> User | None:
    if "user" not in g:
        user_id = session.get("user_id")
        g.user = db.session.get(User, user_id) if user_id else None
    return g.user


def csrf_token() -> str:
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def safe_next(target: str | None) -> str | None:
    """Only a path on this site: an absolute or protocol-relative address would be an open redirect."""
    if not target or "\\" in target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//"):
        return None
    return target


@bp.app_context_processor
def template_globals():
    return {"csrf_token": csrf_token, "user": current_user()}


@bp.before_app_request
def check_csrf():
    """Every POST (sign-in included) must carry the session's token, as a form field or a header."""
    if request.method == "POST":
        expected = session.get("csrf_token", "")
        got = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token", "")
        if not expected or not hmac.compare_digest(expected, got):
            if request.path == "/chat":
                return jsonify(error="Your session has expired. Reload the page and try again."), 400
            abort(400, "The form has expired. Go back, reload the page and try again.")
    return None


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("web.login", next=request.full_path.rstrip("?")))
        return view(*args, **kwargs)

    return wrapper


# -- pages
@bp.get("/")
def index():
    return render_template("index.html")


@bp.get("/healthz")
def healthz():
    return jsonify(status="ok")


@bp.route("/login", methods=["GET", "POST"])
def login():
    target = safe_next(request.values.get("next"))
    if request.method == "GET":
        return render_template("login.html", next=target)
    name = request.form.get("login", "").strip().lower()
    password = request.form.get("password", "")[:MAX_PASSWORD]
    user = (
        db.session.scalar(select(User).where(or_(User.username == name, User.email == name)))
        if name
        else None
    )
    correct = check_password_hash(user.password_hash if user else _DUMMY_HASH, password)
    if user is None or not correct:
        flash("Invalid login credentials", "error")
        return render_template("login.html", next=target), 401
    session.clear()  # a new session at sign-in: nothing planted before it survives
    session["user_id"] = user.id
    return redirect(target or url_for("web.index"))


def _signup_problems(form) -> list[str]:
    problems = []
    if not USERNAME.match(form["username"]):
        problems.append("The username must be 3 to 40 letters, digits, dots, dashes or underscores.")
    if len(form["email"]) > 120 or not EMAIL.match(form["email"]):
        problems.append("Enter a valid email address.")
    for label, key in (("first name", "first_name"), ("last name", "last_name")):
        if not form[key] or len(form[key]) > NAME_MAX:
            problems.append(f"The {label} is required (up to {NAME_MAX} characters).")
    if not MIN_PASSWORD <= len(form["password"]) <= MAX_PASSWORD:
        problems.append(f"The password must be {MIN_PASSWORD} to {MAX_PASSWORD} characters.")
    return problems


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        return render_template("signup.html", form={})
    form = {
        "email": request.form.get("email", "").strip().lower(),
        "username": request.form.get("username", "").strip(),
        "first_name": request.form.get("first_name", "").strip(),
        "last_name": request.form.get("last_name", "").strip(),
        "password": request.form.get("password", ""),
    }
    problems = _signup_problems(form)
    if not problems:
        form["username"] = form["username"].lower()
        taken = db.session.scalar(
            select(func.count())
            .select_from(User)
            .where(or_(User.username == form["username"], User.email == form["email"]))
        )
        if taken:
            problems.append("Username or email already exists.")
    if problems:
        for problem in problems:
            flash(problem, "error")
        form.pop("password")
        return render_template("signup.html", form=form), 400
    user = User(**{k: v for k, v in form.items() if k != "password"})
    user.password_hash = generate_password_hash(form["password"])
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:  # two sign-ups with the same name at the same moment
        db.session.rollback()
        flash("Username or email already exists.", "error")
        form.pop("password")
        return render_template("signup.html", form=form), 400
    flash("Registration successful. Please log in.", "info")
    return redirect(url_for("web.login"))


@bp.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("web.index"))


@bp.get("/profile")
@login_required
def profile():
    return render_template("profile.html")


# -- the chat
def _thread_of(user: User) -> ChatThread:
    """The customer's conversation, created on first use (calls OpenAI, so it happens before any insert)."""
    thread = db.session.scalar(select(ChatThread).where(ChatThread.user_id == user.id))
    if thread is None:
        thread = ChatThread(user_id=user.id, conversation_id=services().assistant.new_conversation())
        db.session.add(thread)
        db.session.commit()
    return thread


@bp.get("/chat")
@login_required
def chat():
    s = services().settings
    thread = db.session.scalar(select(ChatThread).where(ChatThread.user_id == current_user().id))
    return render_template(
        "chat.html",
        messages=thread.messages if thread else [],
        pause_ms=round(s.chat_pause_seconds * 1000),
        ms_per_word=round(s.chat_seconds_per_word * 1000),
        max_typing_ms=round(s.chat_max_typing_seconds * 1000),
        max_chars=s.max_query_chars,
    )


@bp.post("/chat")
def chat_post():
    user = current_user()
    if user is None:
        return jsonify(error="Please sign in again."), 401
    s = services().settings
    query = (
        (request.get_json(silent=True) or {}).get("user_query") if request.is_json else None
    ) or request.form.get("user_query", "")
    query = str(query).strip()
    if not query:
        return jsonify(error="Type a question first."), 400
    if len(query) > s.max_query_chars:
        return jsonify(error=f"Please keep your message under {s.max_query_chars} characters."), 400
    try:
        thread = _thread_of(user)
        reply = services().assistant.reply(
            customer=user.first_name,
            query=query,
            conversation_id=thread.conversation_id,
            user_key=str(user.id),
        )
    except AssistantError:
        return jsonify(error="The assistant is not available right now. Please try again in a moment."), 502
    db.session.add_all(
        [
            ChatMessage(thread_id=thread.id, sender="user", text=query),
            ChatMessage(
                thread_id=thread.id,
                sender="assistant",
                text=reply.text,
                is_order=reply.is_order,
                order_id=reply.order_id or None,
            ),
        ]
    )
    db.session.commit()
    return jsonify(assistant_response=reply.text)
