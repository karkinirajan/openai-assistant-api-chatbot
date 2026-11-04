import pathlib

from lilac_chatbot import create_app
from lilac_chatbot.assistant import SupportAssistant
from lilac_chatbot.config import Settings

from .conftest import login, signup


def test_security_headers_are_on_every_response(client):
    for response in (
        client.get("/"),
        client.get("/no-such-page"),
        client.get("/login"),
        client.get("/healthz"),
    ):
        h = response.headers
        assert (
            "default-src 'self'" in h["Content-Security-Policy"]
            and "frame-ancestors 'none'" in h["Content-Security-Policy"]
        )
        assert h["X-Content-Type-Options"] == "nosniff" and h["X-Frame-Options"] == "DENY"
        assert h["Cache-Control"] == "no-store" and h["Referrer-Policy"] == "same-origin"


def test_the_policy_allows_no_inline_script_or_style_and_no_other_site(client):
    policy = client.get("/").headers["Content-Security-Policy"]
    assert "unsafe-inline" not in policy and "unsafe-eval" not in policy and "http" not in policy


def test_templates_use_no_inline_script_or_style_and_load_nothing_from_other_sites(app):
    """The first version loaded Bootstrap and jQuery from CDNs, with a <style> and <script> in each page."""
    for template in pathlib.Path(app.root_path, "templates").glob("*.html"):
        text = template.read_text()
        assert " style=" not in text and "<style" not in text, template.name
        assert "http://" not in text and "https://" not in text, template.name
        for tag in text.split("<script")[1:]:
            assert tag.lstrip().startswith(("src=", "\n")) or "src=" in tag.split(">")[0], template.name


def test_the_session_cookie_is_httponly_secure_and_samesite(client):
    cookie = client.get("/login").headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie


def test_the_cookie_is_not_secure_when_the_site_is_plain_http_for_local_development(env, openai_fake):
    s = Settings.from_env({**env, "PUBLIC_URL": "http://localhost:5003"})
    local = create_app(s, assistant=SupportAssistant(s, openai_fake.client())).test_client()
    assert "Secure" not in local.get("/login").headers["Set-Cookie"]


def test_debug_mode_is_off_and_there_is_no_console(app, client):
    assert app.debug is False
    assert client.get("/console").status_code == 404


def test_error_pages_use_the_template(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404 and b"Not found" in response.data and b"<html" in response.data
    assert client.put("/signup").status_code == 405


def test_an_oversized_request_is_refused(client):
    csrf = login(client).status_code  # creates the session
    assert csrf in (401, 400, 200, 302)
    response = client.post("/signup", data={"first_name": "x" * 100_000})
    assert response.status_code == 413


def test_nothing_is_cached_even_for_the_chat_page(client):
    signup(client)
    login(client)
    assert client.get("/chat").headers["Cache-Control"] == "no-store"


def test_the_secret_key_comes_from_the_settings_so_sessions_survive_a_restart(env, openai_fake):
    """It used to be os.urandom(24) at every start."""
    s = Settings.from_env(env)
    first = create_app(s, assistant=SupportAssistant(s, openai_fake.client()))
    second = create_app(s, assistant=SupportAssistant(s, openai_fake.client()))
    assert first.secret_key == second.secret_key == s.secret_key
