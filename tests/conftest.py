"""Shared fixtures: demo settings (no real credential anywhere), a fake OpenAI and the app on SQLite."""

import pytest

from lilac_chatbot import create_app
from lilac_chatbot.assistant import SupportAssistant
from lilac_chatbot.config import Settings

from .fake_openai import API_KEY, BASE, FakeOpenAI

SETTINGS_ENV = {
    "OPENAI_API_KEY": API_KEY,
    "SECRET_KEY": "demo-flask-secret-key-0123456789",
    "PUBLIC_URL": "https://assistant.example.test",
    "OPENAI_BASE_URL": BASE,
    "VECTOR_STORE_ID": "vs_demo1",
    "CHAT_PAUSE_SECONDS": "0",
    "CHAT_SECONDS_PER_WORD": "0",
}
OPTIONAL = [
    "OPENAI_MODEL", "DATABASE_URL", "TIMEZONE", "REQUEST_TIMEOUT", "MAX_OUTPUT_TOKENS", "MAX_QUERY_CHARS",
    "CHAT_MAX_TYPING_SECONDS", "SHOPIFY_SHOP", "SHOPIFY_ACCESS_TOKEN", "SHOPIFY_API_VERSION",
]  # fmt: skip


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for name in [*SETTINGS_ENV, *OPTIONAL]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")


@pytest.fixture
def env(tmp_path):
    return {**SETTINGS_ENV, "DATABASE_URL": f"sqlite:///{tmp_path / 'test.db'}"}


@pytest.fixture
def settings(env):
    return Settings.from_env(env)


@pytest.fixture
def openai_fake():
    return FakeOpenAI()


@pytest.fixture
def assistant(settings, openai_fake):
    return SupportAssistant(settings, openai_fake.client())


@pytest.fixture
def app(settings, assistant):
    from lilac_chatbot.extensions import db

    app = create_app(settings, assistant=assistant)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_of(client) -> str:
    """The CSRF token of the client's session (the page that shows a form creates it)."""
    with client.session_transaction() as sess:
        if "csrf_token" not in sess:
            sess["csrf_token"] = "test-csrf-token-" + "x" * 20
        return sess["csrf_token"]


def signup(
    client,
    username="alice",
    email=None,
    first_name="Alice",
    password="correct horse battery",  # noqa: S107
    **extra,
):
    return client.post(
        "/signup",
        data={
            "csrf_token": csrf_of(client), "username": username, "email": email or f"{username}@example.test",
            "first_name": first_name, "last_name": "Tester", "password": password, **extra,
        },
    )  # fmt: skip


def login(client, who="alice", password="correct horse battery", **extra):  # noqa: S107
    return client.post(
        "/login", data={"csrf_token": csrf_of(client), "login": who, "password": password, **extra}
    )


def sign_in(client, username="alice", first_name=None, password="correct horse battery"):  # noqa: S107
    """Create the account and sign in."""
    signup(client, username=username, first_name=first_name or username.title(), password=password)
    return login(client, username, password)


def post_chat(client, query, **kw):
    return client.post("/chat", data={"user_query": query}, headers={"X-CSRF-Token": csrf_of(client)}, **kw)
