import hashlib
from datetime import datetime

import httpx
import openai
import pytest

from lilac_chatbot.assistant import (
    AssistantError,
    SupportAssistant,
    SupportReply,
    clean_order_id,
    parse_reply,
)
from lilac_chatbot.config import Settings

from .conftest import SETTINGS_ENV
from .fake_openai import API_KEY, structured

NOW = datetime(2026, 11, 6, 9, 30)  # a Friday morning


def ask(assistant, **kw):
    args = {"customer": "Jane", "query": "My candle has no scent", "conversation_id": "conv_1", "now": NOW}
    return assistant.reply(**{**args, **kw})


def test_a_reply_returns_the_answer_and_keeps_the_conversation(assistant):
    reply = ask(assistant)
    assert reply.text == "Good morning, Jane! How can I help?" and reply.conversation_id == "conv_1"
    assert reply.is_order is False and reply.order_id == ""


def test_the_request_has_the_shape_the_responses_api_expects(assistant, openai_fake, settings):
    ask(assistant)
    body = openai_fake.body("responses")
    assert body["model"] == settings.openai_model and body["conversation"] == "conv_1"
    assert (
        body["input"] == "My candle has no scent" and body["max_output_tokens"] == settings.max_output_tokens
    )
    assert body["tools"] == [{"type": "file_search", "vector_store_ids": ["vs_demo1"], "max_num_results": 5}]
    assert openai_fake.calls("responses")[0].headers["authorization"] == f"Bearer {API_KEY}"


def test_the_instructions_name_the_customer_and_the_moment_on_every_turn(assistant, openai_fake):
    ask(assistant)
    ask(assistant, query="And the price?")
    for i in (0, 1):
        instructions = openai_fake.body("responses", i)["instructions"]
        assert "As Jessica" in instructions and "======>Jane" in instructions
        assert "======>Good morning" in instructions and "======>Friday" in instructions
    assert openai_fake.body("responses", 1)["input"] == "And the price?"  # the history is in the conversation


def test_the_reply_is_requested_as_a_structured_output(assistant, openai_fake):
    ask(assistant)
    fmt = openai_fake.body("responses")["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True and fmt["name"] == "support_reply"
    schema = fmt["schema"]
    assert sorted(schema["properties"]) == ["answer", "is_order", "order_id"]
    assert (
        sorted(schema["required"]) == ["answer", "is_order", "order_id"]
        and schema["additionalProperties"] is False
    )


def test_the_flag_and_the_order_id_are_returned(assistant, openai_fake):
    openai_fake.answers = [structured("I've arranged a replacement.", is_order=True, order_id="  #1234 ")]
    reply = ask(assistant)
    assert (reply.text, reply.is_order, reply.order_id) == ("I've arranged a replacement.", True, "#1234")


def test_without_a_vector_store_there_is_no_search_tool(env, openai_fake):
    s = Settings.from_env({k: v for k, v in env.items() if k != "VECTOR_STORE_ID"})
    ask(SupportAssistant(s, openai_fake.client()))
    assert "tools" not in openai_fake.body("responses")


def test_only_a_hash_of_the_customer_key_is_sent(assistant, openai_fake):
    ask(assistant, user_key="user-42")
    sent = openai_fake.body("responses")["safety_identifier"]
    assert sent == hashlib.sha256(b"user-42").hexdigest() and "user-42" not in sent
    ask(assistant)
    assert "safety_identifier" not in openai_fake.body("responses")


def test_a_new_conversation_gets_an_id(assistant):
    assert assistant.new_conversation() == "conv_1" and assistant.new_conversation() == "conv_2"


# -- the model's text
def test_text_that_is_not_the_requested_json_is_shown_as_it_is(assistant, openai_fake, caplog):
    """The first version called json.loads on it and failed."""
    openai_fake.answers = ["Sorry, I could not format that."]
    with caplog.at_level("WARNING"):
        reply = ask(assistant)
    assert (reply.text, reply.is_order, reply.order_id) == ("Sorry, I could not format that.", False, "")
    assert "not the requested JSON" in caplog.text


@pytest.mark.parametrize(
    "raw",
    [
        '{"is_order": false, "order_id": "", "answer": "x", "extra": 1}',  # extra keys are refused
        '{"is_order": "yes", "order_id": "", "answer": "x"}',  # a flag that is not a boolean
        '{"answer": "x"}',  # keys missing
        '["a", "list"]',
    ],
)
def test_json_of_the_wrong_shape_counts_as_plain_text(raw):
    assert parse_reply(raw) == (raw, False, "")


def test_a_structured_reply_with_an_empty_answer_is_an_error(assistant, openai_fake):
    openai_fake.answers = [structured("   ")]
    with pytest.raises(AssistantError, match="no answer"):
        ask(assistant)


def test_an_order_id_is_cleaned_before_it_is_stored():
    assert clean_order_id("  #12\n34‮\x00  ") == "#1234"
    assert len(clean_order_id("9" * 500)) == 64


def test_the_reply_model_forbids_extra_keys():
    assert SupportReply.model_json_schema()["additionalProperties"] is False


# -- failures
@pytest.mark.parametrize("status", [400, 401, 429, 500])
def test_openai_failures_become_an_error_that_leaks_nothing(assistant, openai_fake, status):
    openai_fake.fail["responses"] = status
    with pytest.raises(AssistantError) as caught:
        ask(assistant)
    text = str(caught.value)
    assert f"HTTP {status}" in text and "SECRET" not in text and API_KEY not in text


def test_failing_to_create_a_conversation_is_an_error_too(assistant, openai_fake):
    openai_fake.fail["conversations"] = 503
    with pytest.raises(AssistantError, match="HTTP 503"):
        assistant.new_conversation()


def test_a_wrong_key_is_reported_without_showing_it(env, openai_fake):
    s = Settings.from_env({**env, "OPENAI_API_KEY": "another-key-value"})
    transport = httpx.MockTransport(openai_fake.handle)
    client = openai.OpenAI(
        api_key="another-key-value",
        base_url=SETTINGS_ENV["OPENAI_BASE_URL"],
        http_client=httpx.Client(transport=transport),
        max_retries=0,
    )
    with pytest.raises(AssistantError) as caught:
        ask(SupportAssistant(s, client))
    text = str(caught.value)
    assert "HTTP 401" in text and "another-key-value" not in text and API_KEY not in text


def test_a_connection_failure_names_only_its_kind(settings):
    def boom(request):
        raise httpx.ConnectError("could not reach https://x.example.test/?key=SECRET")

    client = openai.OpenAI(
        api_key="k",
        base_url="https://x.example.test/v1",
        http_client=httpx.Client(transport=httpx.MockTransport(boom)),
        max_retries=0,
    )
    with pytest.raises(AssistantError) as caught:
        ask(SupportAssistant(settings, client))
    assert "APIConnectionError" in str(caught.value) and "SECRET" not in str(caught.value)


def test_an_answer_without_text_is_an_error(assistant, openai_fake):
    openai_fake.empty_output = True
    with pytest.raises(AssistantError, match="no text"):
        ask(assistant)


def test_a_blank_answer_is_an_error(assistant, openai_fake):
    openai_fake.answers = ["   \n"]
    with pytest.raises(AssistantError, match="no text"):
        ask(assistant)
