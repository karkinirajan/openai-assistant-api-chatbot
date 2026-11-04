"""Who the chatbot is, and what it is told about the customer in front of it.

The persona text (``data/persona.md``) is the system prompt of the original ``prompt.py``, unchanged except
for the template plumbing at its end. That plumbing filled in the retrieved context, the chat history, the
customer's name, the part of the day and the day of the week; the context and the history now come from
the file search tool and the OpenAI conversation, and the last three are written below the persona on every
request.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from functools import cache
from importlib import resources
from zoneinfo import ZoneInfo

MAX_NAME_CHARS = 60
# Not strftime("%A"): that follows the machine's locale, and the persona's ship-day rule names English days
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@cache
def base_instructions() -> str:
    """The persona, with its one placeholder (``{day_of_week}``) still in it."""
    return resources.files("lilac_chatbot").joinpath("data", "persona.md").read_text(encoding="utf-8").strip()


def part_of_day(now: datetime) -> str:
    """5:00-11:59 morning, 12:00-16:59 afternoon, otherwise evening (the thresholds of the original code)."""
    if 5 <= now.hour < 12:
        return "Good morning"
    if 12 <= now.hour < 17:
        return "Good afternoon"
    return "Good evening"


def weekday(now: datetime) -> str:
    return WEEKDAYS[now.weekday()]


def local_now(timezone: str) -> datetime:
    return datetime.now(ZoneInfo(timezone))


def clean_name(name: str) -> str:
    """A customer's name as it may appear in a prompt: no control or format characters, one line, bounded."""
    # whitespace first: a newline is a control character too, and must become a space, not vanish
    kept = "".join(
        " " if c.isspace() else c for c in name if c.isspace() or not unicodedata.category(c).startswith("C")
    )
    return re.sub(r" {2,}", " ", kept).strip()[:MAX_NAME_CHARS]


def instructions(customer: str, now: datetime) -> str:
    """The system instructions for one reply: the persona, then what is known about this customer and now."""
    name = clean_name(customer) or "unknown"
    persona = base_instructions().replace("{day_of_week}", weekday(now))
    return (
        f"{persona}\n\n"
        "Use the following pieces of context to answer the customers's question.\n\n"
        f"Customer's name  ======>{name}\n"
        f"Part of the day  ======>{part_of_day(now)}\n"
        f"day of the week  ======>{weekday(now)}\n"
    )
