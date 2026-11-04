"""Command line: ``lilac-chatbot run | init-db | init-knowledge | replacements``."""

from __future__ import annotations

import argparse
import collections
import sys
from collections.abc import Sequence
from pathlib import Path

import openai
from dotenv import find_dotenv, load_dotenv
from sqlalchemy import select

from .app import create_app
from .config import ConfigError, Settings
from .extensions import db
from .knowledge import KnowledgeError, create_knowledge_base
from .models import ChatMessage, ChatThread, User
from .shopify import ShopifyCatalog, ShopifyError, catalogue_markdown


def _init_knowledge(args: argparse.Namespace) -> int:
    if not args.file and not args.shopify:
        print("error: nothing to upload. Give --shopify and/or --file PATH.", file=sys.stderr)
        return 2
    settings = Settings.from_env(web=False)
    files: list[Path | tuple[str, bytes]] = [Path(f) for f in args.file]
    try:
        if args.shopify:
            products = ShopifyCatalog(settings).products()
            if not products:
                print("error: Shopify returned no active products.", file=sys.stderr)
                return 3
            files.append(("products.md", catalogue_markdown(products, shop=settings.shopify_shop).encode()))
            print(f"Read {len(products)} active products from Shopify.")
        client = openai.OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            timeout=settings.request_timeout,
        )
        store_id = create_knowledge_base(client, files)
    except (KnowledgeError, ShopifyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"Uploaded {len(files)} file(s). Put this in your .env, then restart the app:")
    print(f"VECTOR_STORE_ID={store_id}")
    return 0


def _replacements() -> int:
    """List the replies in which the assistant flagged a replacement or order request, by month.

    The persona tells the customer a replacement has been arranged, but nothing in this project creates an
    order: this list is what a person works from.
    """
    app = create_app(create_tables=False)
    with app.app_context():
        rows = db.session.execute(
            select(ChatMessage.created_at, User.username, ChatMessage.order_id, ChatMessage.text)
            .join(ChatThread, ChatMessage.thread_id == ChatThread.id)
            .join(User, ChatThread.user_id == User.id)
            .where(ChatMessage.sender == "assistant", ChatMessage.is_order.is_(True))
            .order_by(ChatMessage.id)
        ).all()
    if not rows:
        print("No replacement or order requests so far.")
        return 0
    by_month: collections.Counter[str] = collections.Counter()
    for created, username, order_id, text in rows:
        by_month[created.strftime("%Y-%m")] += 1
        snippet = " ".join(text.split())[:60]
        print(f"{created:%Y-%m-%d %H:%M}  {username}  order {order_id or '-'}  {snippet}")
    print("By month: " + ", ".join(f"{month}: {n}" for month, n in sorted(by_month.items())))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lilac-chatbot")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start a development server (use gunicorn in production)")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=5003)
    sub.add_parser("init-db", help="create the database tables")
    sub.add_parser("replacements", help="list the replacement and order requests the assistant flagged")
    know = sub.add_parser("init-knowledge", help="upload files to a new OpenAI vector store")
    know.add_argument("--file", action="append", default=[], help="a file to upload (repeatable)")
    know.add_argument("--shopify", action="store_true", help="upload the active Shopify products")
    args = parser.parse_args(argv)

    load_dotenv(find_dotenv(usecwd=True))  # a .env in the current directory; the real environment wins
    try:
        if args.command == "init-knowledge":
            return _init_knowledge(args)
        if args.command == "replacements":
            return _replacements()
        app = create_app(create_tables=args.command == "init-db")
    except ConfigError as exc:
        print(f"error: {exc}. See .env.example.", file=sys.stderr)
        return 2
    if args.command == "init-db":
        print("Database tables created.")
        return 0
    # Never in debug mode: the first version ran that way, which exposes the Werkzeug console to whoever
    # can reach the port.
    app.run(host=args.host, port=args.port, debug=False)
    return 0
