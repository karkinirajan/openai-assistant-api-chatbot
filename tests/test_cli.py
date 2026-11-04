import datetime
import sqlite3
from pathlib import Path

from flask import Flask

from lilac_chatbot import cli
from lilac_chatbot.extensions import db
from lilac_chatbot.models import ChatMessage
from lilac_chatbot.shopify import Product, ShopifyError

from .conftest import post_chat, sign_in
from .fake_openai import API_KEY, structured


def apply_env(monkeypatch, env):
    for name, value in env.items():
        monkeypatch.setenv(name, value)


def test_a_missing_configuration_exits_2_naming_the_variables(capsys):
    assert cli.main(["init-db"]) == 2
    err = capsys.readouterr().err
    assert "OPENAI_API_KEY" in err and "SECRET_KEY" in err and ".env.example" in err


def test_init_db_creates_the_tables(monkeypatch, env, tmp_path, capsys):
    apply_env(monkeypatch, env)
    assert cli.main(["init-db"]) == 0
    assert "tables created" in capsys.readouterr().out
    conn = sqlite3.connect(tmp_path / "test.db")
    try:
        tables = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        columns = {r[1] for r in conn.execute("pragma table_info(chat_message)")}
    finally:
        conn.close()
    assert {"user", "chat_thread", "chat_message"} <= tables and {"is_order", "order_id"} <= columns


def test_run_starts_the_server_without_debug(monkeypatch, env):
    apply_env(monkeypatch, env)
    seen = {}
    monkeypatch.setattr(Flask, "run", lambda self, **kwargs: seen.update(kwargs))
    assert cli.main(["run", "--port", "5055"]) == 0
    assert seen == {"host": "127.0.0.1", "port": 5055, "debug": False}


def test_a_dotenv_file_in_the_current_directory_is_read(monkeypatch, env, tmp_path):
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED")
    (tmp_path / ".env").write_text("".join(f"{k}={v}\n" for k, v in env.items()))
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init-db"]) == 0


# -- init-knowledge
def knowledge_env(monkeypatch, env, fake):
    apply_env(monkeypatch, env)
    client = fake.client()  # made first: it is built with openai.OpenAI, which is patched next
    monkeypatch.setattr(cli.openai, "OpenAI", lambda **kwargs: client)


def test_init_knowledge_needs_something_to_upload(monkeypatch, env, openai_fake, capsys):
    knowledge_env(monkeypatch, env, openai_fake)
    assert cli.main(["init-knowledge"]) == 2
    assert "--shopify" in capsys.readouterr().err and openai_fake.requests == []


def test_init_knowledge_uploads_files_and_prints_the_store_id(
    monkeypatch, env, openai_fake, tmp_path, capsys
):
    knowledge_env(monkeypatch, env, openai_fake)
    (tmp_path / "faq.md").write_text("# FAQ")
    (tmp_path / "policy.md").write_text("# Policy")
    assert (
        cli.main(
            ["init-knowledge", "--file", str(tmp_path / "faq.md"), "--file", str(tmp_path / "policy.md")]
        )
        == 0
    )
    assert "VECTOR_STORE_ID=vs_demo1" in capsys.readouterr().out
    assert openai_fake.uploaded == ["faq.md", "policy.md"]


def test_init_knowledge_needs_only_the_openai_key(monkeypatch, openai_fake, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", API_KEY)
    client = openai_fake.client()
    monkeypatch.setattr(cli.openai, "OpenAI", lambda **kwargs: client)
    (tmp_path / "faq.md").write_text("# FAQ")
    assert cli.main(["init-knowledge", "--file", str(tmp_path / "faq.md")]) == 0


def test_init_knowledge_reports_an_openai_failure_without_leaking(
    monkeypatch, env, openai_fake, tmp_path, capsys
):
    knowledge_env(monkeypatch, env, openai_fake)
    (tmp_path / "faq.md").write_text("# FAQ")
    openai_fake.fail["vector_stores"] = 500
    assert cli.main(["init-knowledge", "--file", str(tmp_path / "faq.md")]) == 3
    err = capsys.readouterr().err
    assert "HTTP 500" in err and "SECRET" not in err and API_KEY not in err


class FakeCatalog:
    def __init__(self, settings):
        self.settings = settings

    def products(self):
        return [Product("Rose Candle", "rose", "Soy wax", "Candle", "Lilac", (), "12.0", "12.0", "USD", True)]


SHOP_ENV = {"SHOPIFY_SHOP": "demo.myshopify.com", "SHOPIFY_ACCESS_TOKEN": "demo-shop-token"}


def test_init_knowledge_can_upload_the_shopify_catalogue(monkeypatch, env, openai_fake, capsys):
    knowledge_env(monkeypatch, {**env, **SHOP_ENV}, openai_fake)
    monkeypatch.setattr(cli, "ShopifyCatalog", FakeCatalog)
    assert cli.main(["init-knowledge", "--shopify"]) == 0
    assert openai_fake.uploaded == ["products.md"] and "Read 1 active products" in capsys.readouterr().out


def test_init_knowledge_shopify_without_credentials_exits_3(monkeypatch, env, openai_fake, capsys):
    knowledge_env(monkeypatch, env, openai_fake)
    assert cli.main(["init-knowledge", "--shopify"]) == 3
    assert "SHOPIFY_SHOP" in capsys.readouterr().err and openai_fake.requests == []


def test_init_knowledge_with_no_active_products_stops(monkeypatch, env, openai_fake):
    knowledge_env(monkeypatch, {**env, **SHOP_ENV}, openai_fake)
    monkeypatch.setattr(cli, "ShopifyCatalog", lambda s: type("C", (), {"products": lambda self: []})())
    assert cli.main(["init-knowledge", "--shopify"]) == 3
    assert openai_fake.requests == []


def test_a_shopify_failure_stops_before_anything_is_uploaded(monkeypatch, env, openai_fake, capsys):
    knowledge_env(monkeypatch, {**env, **SHOP_ENV}, openai_fake)

    class Failing:
        def __init__(self, settings):
            pass

        def products(self):
            raise ShopifyError("Shopify answered HTTP 401")

    monkeypatch.setattr(cli, "ShopifyCatalog", Failing)
    assert cli.main(["init-knowledge", "--shopify"]) == 3
    assert "HTTP 401" in capsys.readouterr().err and openai_fake.requests == []


# -- replacements
def test_replacements_with_nothing_flagged(monkeypatch, env, capsys):
    apply_env(monkeypatch, env)
    assert cli.main(["init-db"]) == 0
    capsys.readouterr()
    assert cli.main(["replacements"]) == 0
    assert "No replacement or order requests" in capsys.readouterr().out


def test_replacements_lists_the_flagged_replies_and_counts_them_by_month(
    app, monkeypatch, env, openai_fake, capsys
):
    a, b = app.test_client(), app.test_client()
    sign_in(a, "alice")
    sign_in(b, "bob")
    openai_fake.answers = [
        structured("I've arranged a replacement.", is_order=True, order_id="#1234"),
        structured("Happy to help with that.", is_order=False),
        structured("Your replacement\nwill ship tomorrow.", is_order=True, order_id=""),
    ]
    post_chat(a, "Please replace order #1234")
    post_chat(a, "Another question")
    post_chat(b, "Replace my candle")
    with app.app_context():  # one of them was in an earlier month
        first = db.session.scalars(
            db.select(ChatMessage).where(ChatMessage.is_order.is_(True)).order_by(ChatMessage.id)
        ).first()
        first.created_at = datetime.datetime(2026, 10, 15, 9, 30)
        later = db.session.scalars(
            db.select(ChatMessage).where(ChatMessage.is_order.is_(True)).order_by(ChatMessage.id)
        ).all()[-1]
        later.created_at = datetime.datetime(2026, 11, 2, 14, 5)
        db.session.commit()
    apply_env(monkeypatch, env)
    assert cli.main(["replacements"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "2026-10-15 09:30  alice  order #1234  I've arranged a replacement."
    assert (
        lines[1] == "2026-11-02 14:05  bob  order -  Your replacement will ship tomorrow."
    )  # one line, no order id
    assert (
        lines[2] == "By month: 2026-10: 1, 2026-11: 1" and len(lines) == 3
    )  # the unflagged reply is not listed


def test_the_persona_ships_with_the_package():
    data = Path(cli.__file__).parent / "data"
    assert "Jessica" in (data / "persona.md").read_text()


def test_replacements_never_prints_control_characters_even_from_a_hand_edited_database(
    app, monkeypatch, env, capsys
):
    client = app.test_client()
    sign_in(client, "alice")
    post_chat(client, "Please replace order #1234")
    with app.app_context():
        message = db.session.scalars(db.select(ChatMessage).where(ChatMessage.sender == "assistant")).one()
        message.is_order = True
        message.text = (
            "\x1b[2J\x1b]0;owned\x07Hi\u202e\nsecond line"  # stored by some other route than the app
        )
        db.session.commit()
    apply_env(monkeypatch, env)
    assert cli.main(["replacements"]) == 0
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out and "\u202e" not in out
    assert out.splitlines()[0].endswith("[2J]0;ownedHi second line") and len(out.splitlines()) == 2
