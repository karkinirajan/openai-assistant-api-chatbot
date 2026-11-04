from lilac_chatbot.extensions import db
from lilac_chatbot.models import ChatMessage, ChatThread

from .conftest import csrf_of, login, post_chat, sign_in, signup
from .fake_openai import structured


def messages(app):
    with app.app_context():
        return [
            (m.sender, m.text) for m in db.session.scalars(db.select(ChatMessage).order_by(ChatMessage.id))
        ]


def test_the_chat_page_needs_a_login(client):
    response = client.get("/chat")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_posting_without_a_login_is_a_401_json_not_a_redirect(client, openai_fake):
    response = post_chat(client, "hello")
    assert response.status_code == 401 and "sign in" in response.get_json()["error"].lower()
    assert openai_fake.requests == []


def test_a_message_is_answered_and_both_sides_are_stored(app, client, openai_fake):
    sign_in(client)
    response = post_chat(client, "My candle has no scent")
    assert response.status_code == 200
    assert response.get_json() == {"assistant_response": "Good morning, Jane! How can I help?"}
    assert messages(app) == [
        ("user", "My candle has no scent"),
        ("assistant", "Good morning, Jane! How can I help?"),
    ]


def test_the_instructions_name_the_customer_by_first_name_and_the_message_is_sent_as_it_is(
    client, openai_fake
):
    sign_in(client, first_name="Janet")
    post_chat(client, "My candle has no scent")
    post_chat(client, "And the price?")
    for i, query in enumerate(("My candle has no scent", "And the price?")):
        body = openai_fake.body("responses", i)
        assert (
            body["input"] == query
        )  # no greeting request is added: the persona decides from the conversation
        assert (
            "======>Janet" in body["instructions"] and "Tester" not in body["instructions"]
        )  # first name only


def test_the_conversation_is_created_once_and_reused(app, client, openai_fake):
    sign_in(client)
    post_chat(client, "one")
    post_chat(client, "two")
    post_chat(client, "three")
    assert len(openai_fake.calls("conversations")) == 1
    assert {openai_fake.body("responses", i)["conversation"] for i in range(3)} == {"conv_1"}
    with app.app_context():
        assert db.session.scalars(db.select(ChatThread)).one().conversation_id == "conv_1"


def test_the_customer_is_identified_to_openai_only_by_a_hash(client, openai_fake):
    sign_in(client)
    post_chat(client, "hi")
    body = openai_fake.body("responses")
    assert len(body["safety_identifier"]) == 64 and "alice" not in str(body).replace("Alice", "")


def test_a_json_body_works_too(client, openai_fake):
    sign_in(client)
    response = client.post("/chat", json={"user_query": "hello"}, headers={"X-CSRF-Token": csrf_of(client)})
    assert response.status_code == 200


def test_the_chat_post_needs_the_csrf_token(client, openai_fake):
    sign_in(client)
    assert client.post("/chat", data={"user_query": "hi"}).status_code == 400
    wrong = client.post("/chat", data={"user_query": "hi"}, headers={"X-CSRF-Token": "wrong"})
    assert wrong.status_code == 400 and "expired" in wrong.get_json()["error"]
    assert openai_fake.requests == []


def test_an_empty_message_is_refused_without_calling_openai(client, openai_fake):
    sign_in(client)
    assert post_chat(client, "   ").status_code == 400
    assert openai_fake.requests == []


def test_a_very_long_message_is_refused_without_calling_openai(client, openai_fake, settings):
    sign_in(client)
    response = post_chat(client, "x" * (settings.max_query_chars + 1))
    assert response.status_code == 400 and str(settings.max_query_chars) in response.get_json()["error"]
    assert openai_fake.requests == []
    assert post_chat(client, "x" * settings.max_query_chars).status_code == 200


def test_an_openai_failure_is_a_502_with_a_generic_message_and_stores_nothing(app, client, openai_fake):
    sign_in(client)
    openai_fake.fail["responses"] = 500
    response = post_chat(client, "hello")
    assert response.status_code == 502 and "not available" in response.get_json()["error"]
    assert "SECRET" not in response.get_data(as_text=True) and "demo-openai-key" not in response.get_data(
        as_text=True
    )
    assert messages(app) == []
    openai_fake.fail.clear()
    assert post_chat(client, "hello again").status_code == 200  # and it recovers


def test_failing_to_start_a_conversation_is_a_502_too(app, client, openai_fake):
    sign_in(client)
    openai_fake.fail["conversations"] = 503
    assert post_chat(client, "hello").status_code == 502
    with app.app_context():
        assert db.session.scalars(db.select(ChatThread)).all() == []  # no half-made thread


def test_customers_have_separate_conversations_and_histories(app, openai_fake):
    a, b = app.test_client(), app.test_client()
    sign_in(a, "alice")
    sign_in(b, "bob")
    openai_fake.answers = [structured("Alice-only answer"), structured("Bob-only answer")]
    post_chat(a, "Alice private question")
    post_chat(b, "Bob private question")
    assert {openai_fake.body("responses", i)["conversation"] for i in (0, 1)} == {"conv_1", "conv_2"}
    page_a, page_b = a.get("/chat").data, b.get("/chat").data
    assert b"Alice private question" in page_a and b"Alice-only answer" in page_a
    assert b"Bob private question" not in page_a and b"Bob-only answer" not in page_a
    assert b"Bob private question" in page_b and b"Alice private question" not in page_b


def test_the_history_is_shown_again_on_the_page_and_escaped(client, openai_fake):
    sign_in(client)
    openai_fake.answers = [structured("<img src=x onerror=alert(1)> done")]
    post_chat(client, "<script>alert(1)</script>")
    page = client.get("/chat").data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in page and b"<script>alert" not in page
    assert b"<img src=x" not in page


def test_the_page_passes_the_typing_settings_to_the_script(env, openai_fake):
    from lilac_chatbot import create_app
    from lilac_chatbot.assistant import SupportAssistant
    from lilac_chatbot.config import Settings

    s = Settings.from_env(
        {**env, "CHAT_PAUSE_SECONDS": "10", "CHAT_SECONDS_PER_WORD": "0.66", "CHAT_MAX_TYPING_SECONDS": "30"}
    )
    c = create_app(s, assistant=SupportAssistant(s, openai_fake.client())).test_client()
    signup(c)
    login(c)
    page = c.get("/chat").data
    for attr in (b'data-pause-ms="10000"', b'data-ms-per-word="660"', b'data-max-typing-ms="30000"'):
        assert attr in page


def test_the_customer_sees_the_answer_not_the_json_and_the_flag_is_stored(app, client, openai_fake):
    sign_in(client)
    openai_fake.answers = [
        structured("I've arranged a replacement for you.", is_order=True, order_id="#1234")
    ]
    response = post_chat(client, "Please replace order #1234, the rose candle")
    assert response.get_json() == {"assistant_response": "I've arranged a replacement for you."}
    with app.app_context():
        user_msg, assistant_msg = db.session.scalars(db.select(ChatMessage).order_by(ChatMessage.id)).all()
        assert (user_msg.is_order, user_msg.order_id) == (False, None)
        assert (assistant_msg.text, assistant_msg.is_order, assistant_msg.order_id) == (
            "I've arranged a replacement for you.", True, "#1234")  # fmt: skip
    page = client.get("/chat").data
    assert b"I&#39;ve arranged a replacement" in page and b"is_order" not in page and b"order_id" not in page


def test_a_general_question_is_not_flagged(app, client):
    sign_in(client)
    post_chat(client, "What are your opening hours?")
    with app.app_context():
        assert [m.is_order for m in db.session.scalars(db.select(ChatMessage))] == [False, False]


def test_an_answer_that_is_not_json_is_still_shown(app, client, openai_fake):
    """The first version called json.loads on the model's text, so this was a 500 error."""
    sign_in(client)
    openai_fake.answers = ["Sorry, something went wrong with my formatting."]
    response = post_chat(client, "hello")
    assert response.status_code == 200 and "something went wrong" in response.get_json()["assistant_response"]
    with app.app_context():
        assert (
            db.session.scalars(db.select(ChatMessage).where(ChatMessage.sender == "assistant")).one().is_order
            is False
        )
