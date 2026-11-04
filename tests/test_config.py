import pytest

from lilac_chatbot.config import DEFAULT_MODEL, ConfigError, Settings

MINIMAL = {"OPENAI_API_KEY": "demo-openai-key", "SECRET_KEY": "0123456789abcdef"}


def test_defaults():
    s = Settings.from_env(MINIMAL)
    assert s.openai_model == DEFAULT_MODEL and s.timezone == "America/Chicago"
    assert s.public_url == "http://localhost:5003" and not s.cookie_secure
    assert (s.chat_pause_seconds, s.chat_seconds_per_word, s.chat_max_typing_seconds) == (10.0, 0.66, 30.0)
    assert s.vector_store_id == "" and not s.shopify_configured and s.shopify_api_version == "2026-10"


def test_secrets_are_not_in_the_repr():
    s = Settings.from_env(
        {**MINIMAL, "SHOPIFY_SHOP": "demo.myshopify.com", "SHOPIFY_ACCESS_TOKEN": "demo-shop-token"}
    )
    text = repr(s)
    for secret in ("demo-openai-key", "0123456789abcdef", "demo-shop-token"):
        assert secret not in text
    assert "demo.myshopify.com" in text


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "SECRET_KEY"])
def test_a_missing_required_variable_is_named(missing):
    env = {k: v for k, v in MINIMAL.items() if k != missing}
    with pytest.raises(ConfigError, match=missing):
        Settings.from_env(env)


def test_command_line_jobs_need_only_the_openai_key():
    s = Settings.from_env({"OPENAI_API_KEY": "demo-openai-key"}, web=False)
    assert s.secret_key == ""
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        Settings.from_env({}, web=False)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"SECRET_KEY": "short"}, "at least 16"),
        ({"PUBLIC_URL": "localhost:5003"}, "PUBLIC_URL"),
        ({"TIMEZONE": "Mars/Olympus"}, "TIMEZONE"),
        ({"VECTOR_STORE_ID": "file-123"}, "VECTOR_STORE_ID"),
        ({"REQUEST_TIMEOUT": "0"}, "REQUEST_TIMEOUT"),
        ({"REQUEST_TIMEOUT": "soon"}, "REQUEST_TIMEOUT"),
        ({"MAX_OUTPUT_TOKENS": "3"}, "MAX_OUTPUT_TOKENS"),
        ({"CHAT_PAUSE_SECONDS": "-1"}, "CHAT_PAUSE_SECONDS"),
        ({"CHAT_SECONDS_PER_WORD": "nan"}, "CHAT_SECONDS_PER_WORD"),
        ({"SHOPIFY_SHOP": "demo.myshopify.com"}, "both"),
        ({"SHOPIFY_ACCESS_TOKEN": "demo-shop-token"}, "both"),
        ({"SHOPIFY_SHOP": "evil.example.test", "SHOPIFY_ACCESS_TOKEN": "t"}, r"\*\.myshopify\.com"),
        ({"SHOPIFY_API_VERSION": "latest"}, "SHOPIFY_API_VERSION"),
    ],
)
def test_invalid_values_are_rejected(change, message):
    with pytest.raises(ConfigError, match=message):
        Settings.from_env({**MINIMAL, **change})


def test_the_error_never_contains_the_value():
    with pytest.raises(ConfigError) as caught:
        Settings.from_env(
            {**MINIMAL, "SHOPIFY_SHOP": "evil.example.test", "SHOPIFY_ACCESS_TOKEN": "demo-shop-token"}
        )
    assert "demo-shop-token" not in str(caught.value) and "evil.example.test" not in str(caught.value)


def test_overrides_are_read():
    s = Settings.from_env(
        {
            **MINIMAL,
            "OPENAI_MODEL": " other-model ",
            "PUBLIC_URL": "https://shop.example.test/",
            "TIMEZONE": "Europe/Paris",
            "VECTOR_STORE_ID": "vs_abc123",
            "MAX_QUERY_CHARS": "500",
            "SHOPIFY_SHOP": "Demo.MyShopify.com",
            "SHOPIFY_ACCESS_TOKEN": "demo-shop-token",
            "SHOPIFY_API_VERSION": "2026-07",
        }
    )
    assert (s.openai_model, s.public_url, s.cookie_secure) == (
        "other-model",
        "https://shop.example.test",
        True,
    )
    assert (s.timezone, s.vector_store_id, s.max_query_chars) == ("Europe/Paris", "vs_abc123", 500)
    assert (
        s.shopify_configured and s.shopify_shop == "demo.myshopify.com" and s.shopify_api_version == "2026-07"
    )
