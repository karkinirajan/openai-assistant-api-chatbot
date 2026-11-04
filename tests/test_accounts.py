import pytest

from lilac_chatbot.extensions import db
from lilac_chatbot.models import User

from .conftest import csrf_of, login, signup


def users(app):
    with app.app_context():
        return db.session.scalars(db.select(User)).all()


def test_signup_creates_an_account_with_a_hashed_password(app, client):
    response = signup(client)
    assert response.status_code == 302 and response.headers["Location"].endswith("/login")
    (user,) = users(app)
    assert (user.username, user.email, user.first_name) == ("alice", "alice@example.test", "Alice")
    assert user.password_hash != "correct horse battery" and "correct horse" not in user.password_hash
    assert b"Registration successful" in client.get("/login").data


def test_usernames_and_emails_are_case_insensitive(app, client):
    signup(client, username="Alice", email="Alice@Example.TEST")
    (user,) = users(app)
    assert (user.username, user.email) == ("alice", "alice@example.test")
    again = signup(client, username="ALICE", email="other@example.test")
    assert again.status_code == 400 and b"already exists" in again.data
    assert len(users(app)) == 1


def test_a_duplicate_email_is_refused(app, client):
    signup(client)
    again = signup(client, username="bob", email="ALICE@example.test")
    assert again.status_code == 400 and len(users(app)) == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"username": "ab"}, b"username must be"),
        ({"username": "has space"}, b"username must be"),
        ({"email": "not-an-email"}, b"valid email"),
        ({"password": "short"}, b"password must be"),
        ({"password": "x" * 129}, b"password must be"),
        ({"first_name": ""}, b"first name is required"),
        ({"last_name": "L" * 101}, b"last name is required"),
    ],
)
def test_invalid_sign_ups_are_refused_with_a_reason(app, client, change, message):
    response = signup(client, **change)
    assert response.status_code == 400 and message in response.data and users(app) == []


def test_the_form_keeps_what_was_typed_but_never_the_password(client):
    response = signup(client, username="bo", password="secret-password-123", first_name="Bo")
    assert b'value="Bo"' in response.data and b"secret-password-123" not in response.data


def test_everything_typed_is_escaped(client):
    response = signup(client, username="bo", first_name='"><script>alert(1)</script>')
    assert b"<script>alert(1)" not in response.data


def test_login_by_username_or_email_in_any_case(client):
    signup(client)
    for who in ("alice", "ALICE", "alice@example.test", "Alice@Example.Test"):
        client.post("/logout", data={"csrf_token": csrf_of(client)})
        assert login(client, who).status_code == 302, who
        assert b"Logout" in client.get("/").data


@pytest.mark.parametrize("who", ["alice", "nobody"])
def test_a_wrong_password_and_an_unknown_account_get_the_same_answer(client, who):
    signup(client)
    response = login(client, who, password="wrong password here")
    assert response.status_code == 401 and b"Invalid login credentials" in response.data
    assert b"Logout" not in client.get("/").data


def test_an_empty_login_is_refused(client):
    assert login(client, "", password="").status_code == 401


def test_signing_in_starts_a_fresh_session(client):
    signup(client)
    with client.session_transaction() as sess:
        sess["planted"] = "by an attacker"
    assert login(client).status_code == 302
    with client.session_transaction() as sess:
        assert "planted" not in sess and "user_id" in sess


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/profile", "/profile"),
        ("/chat?x=1", "/chat?x=1"),
        ("https://evil.example.test/", "/"),
        ("//evil.example.test/", "/"),
        ("/\\evil.example.test", "/"),
        ("javascript:alert(1)", "/"),
        ("profile", "/"),
        ("", "/"),
    ],
)
def test_only_a_path_on_this_site_can_follow_a_login(client, target, expected):
    signup(client)
    response = login(client, next=target)
    assert response.status_code == 302 and response.headers["Location"] == expected


def test_a_page_that_needs_a_login_sends_you_back_to_it(client):
    response = client.get("/profile")
    assert response.status_code == 302 and response.headers["Location"] == "/login?next=/profile"
    signup(client)
    assert login(client, next="/profile").headers["Location"] == "/profile"


def test_logout_needs_a_post_with_the_token(client):
    signup(client)
    login(client)
    assert client.get("/logout").status_code == 405
    assert client.post("/logout").status_code == 400
    assert client.post("/logout", data={"csrf_token": "wrong"}).status_code == 400
    assert b"Logout" in client.get("/").data  # still signed in
    assert client.post("/logout", data={"csrf_token": csrf_of(client)}).status_code == 302
    assert b"Logout" not in client.get("/").data


def test_every_form_post_needs_the_csrf_token(client):
    for path in ("/signup", "/login", "/logout"):
        assert client.post(path, data={"username": "x"}).status_code == 400, path
        assert client.post(path, data={"csrf_token": "wrong"}).status_code == 400, path


def test_the_profile_shows_only_the_signed_in_customer(app):
    a, b = app.test_client(), app.test_client()
    signup(a, username="alice")
    login(a, "alice")
    signup(b, username="bob")
    login(b, "bob")
    page_a, page_b = a.get("/profile").data, b.get("/profile").data
    assert b"alice@example.test" in page_a and b"bob@example.test" not in page_a
    assert b"bob@example.test" in page_b and b"alice@example.test" not in page_b


def test_the_profile_never_shows_the_password_hash(client):
    signup(client)
    login(client)
    assert b"scrypt" not in client.get("/profile").data and b"pbkdf2" not in client.get("/profile").data


def test_the_home_page_and_health_check(client):
    assert client.get("/").status_code == 200 and b"Log in to chat" in client.get("/").data
    assert client.get("/healthz").get_json() == {"status": "ok"}


def test_an_unknown_account_still_costs_one_password_hash_check(client, monkeypatch):
    """So that "no such account" cannot be told from "wrong password" by how long the answer takes."""
    from lilac_chatbot import views

    seen = []
    real = views.check_password_hash
    monkeypatch.setattr(
        views, "check_password_hash", lambda stored, given: seen.append(stored) or real(stored, given)
    )
    assert login(client, "nobody", password="whatever password").status_code == 401
    assert len(seen) == 1
