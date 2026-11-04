"""Customers, and the one conversation each of them has with the assistant.

The first version defined ``ChatThread`` and ``ChatMessage`` but never saved a message: the chat route started
from an empty history every time. A conversation now lives in OpenAI (its id is stored here), and the messages
are kept here too so that the page can show them again.
"""

from __future__ import annotations

import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db


def utcnow() -> datetime.datetime:
    """Naive UTC (datetime.utcnow() is deprecated); the columns store naive UTC."""
    return datetime.datetime.now(datetime.UTC).replace(tzinfo=None)


class User(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(120), unique=True)  # stored in lower case
    username: Mapped[str] = mapped_column(String(40), unique=True)  # stored in lower case
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    thread: Mapped[ChatThread | None] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class ChatThread(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), unique=True)  # one conversation per customer
    conversation_id: Mapped[str] = mapped_column(String(255))  # OpenAI's conversation id
    user: Mapped[User] = relationship(back_populates="thread")
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="thread", order_by="ChatMessage.id", cascade="all, delete-orphan"
    )


class ChatMessage(db.Model):
    id: Mapped[int] = mapped_column(primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("chat_thread.id"))
    sender: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    text: Mapped[str] = mapped_column(Text)
    # Set on an assistant message when the customer asked for a replacement or an order
    # (listed by `lilac-chatbot replacements`)
    is_order: Mapped[bool] = mapped_column(default=False)
    order_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=utcnow)
    thread: Mapped[ChatThread] = relationship(back_populates="messages")
