"""The chatbot: one OpenAI Responses API call per customer message.

The persona asks for a JSON answer with ``is_order``, ``order_id`` and ``answer``. The first version parsed
it with ``json.loads`` and raised an error whenever the model had not produced valid JSON; the request now
asks for that shape as a structured output, and an answer that still is not that JSON is shown as plain text.

Errors raised here never contain the text of an OpenAI error: those messages can quote part of the API key.
"""

from __future__ import annotations

import hashlib
import logging
import unicodedata
from dataclasses import dataclass
from datetime import datetime

import openai
from pydantic import BaseModel, ConfigDict, ValidationError

from . import persona
from .config import Settings

logger = logging.getLogger(__name__)

MAX_SEARCH_RESULTS = 5
MAX_ORDER_ID_CHARS = 64


class SupportReply(BaseModel):
    """The shape the persona asks for."""

    # strict: the flag triggers a person's work, so "yes" or 1 must not be coerced into True
    model_config = ConfigDict(extra="forbid", strict=True)

    is_order: bool  # the customer asked for a replacement or an order and gave an order id and a product
    order_id: str  # "" when there is none
    answer: str  # what the customer is shown


REPLY_FORMAT = {
    "type": "json_schema",
    "name": "support_reply",
    "schema": SupportReply.model_json_schema(),
    "strict": True,
}


class AssistantError(Exception):
    """OpenAI could not answer. The message is safe to show to the chatbot's operator."""


@dataclass(frozen=True, slots=True)
class Reply:
    text: str
    conversation_id: str
    is_order: bool = False
    order_id: str = ""


def _describe(exc: openai.OpenAIError) -> str:
    """Kind and HTTP status of a failure, without the message."""
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ + (f", HTTP {status}" if status else "")


# Kept when text is cleaned: a reply has line breaks and tabs, and U+200D joins the parts of an emoji
_KEEP = frozenset("\n\t\u200d")


def clean_answer(text: str) -> str:
    """A reply as it may be stored: no control or format characters (an ESC would drive a terminal, a
    right-to-left override would reorder what a person reads), except line breaks, tabs and emoji joiners."""
    return "".join(c for c in text if c in _KEEP or not unicodedata.category(c).startswith("C")).strip()


def clean_order_id(value: str) -> str:
    """An order id as it may be stored and shown to staff: one line, no control characters, bounded."""
    kept = "".join(c for c in value if not unicodedata.category(c).startswith("C"))
    return kept.strip()[:MAX_ORDER_ID_CHARS]


def parse_reply(raw: str) -> tuple[str, bool, str]:
    """(answer, is_order, order_id) from the model's text."""
    try:
        parsed = SupportReply.model_validate_json(raw)
    except ValidationError:
        logger.warning("OpenAI answered with text that is not the requested JSON; showing it as it is")
        return clean_answer(raw), False, ""
    return clean_answer(parsed.answer), parsed.is_order, clean_order_id(parsed.order_id)


class SupportAssistant:
    def __init__(self, settings: Settings, client: openai.OpenAI | None = None) -> None:
        self._settings = settings
        self._client = client or openai.OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url or None,
            timeout=settings.request_timeout,
        )

    def new_conversation(self) -> str:
        """An empty conversation. OpenAI keeps its items, so the earlier messages need not be sent again."""
        try:
            return self._client.conversations.create().id
        except openai.OpenAIError as exc:
            logger.warning("Creating a conversation failed (%s)", _describe(exc))
            raise AssistantError(f"OpenAI request failed ({_describe(exc)})") from None

    def reply(
        self,
        *,
        customer: str,
        query: str,
        conversation_id: str,
        user_key: str = "",
        now: datetime | None = None,
    ) -> Reply:
        """Answer one customer message inside a conversation.

        `customer` is the customer's first name. `user_key` is an opaque id of the customer (never their name
        or email); it is hashed before it is sent as OpenAI's ``safety_identifier``.
        """
        s = self._settings
        kwargs: dict = {}
        if s.vector_store_id:
            kwargs["tools"] = [
                {
                    "type": "file_search",
                    "vector_store_ids": [s.vector_store_id],
                    "max_num_results": MAX_SEARCH_RESULTS,
                }
            ]
        if user_key:
            kwargs["safety_identifier"] = hashlib.sha256(user_key.encode()).hexdigest()
        try:
            response = self._client.responses.create(
                model=s.openai_model,
                # Instructions are not carried over from one response to the next: send them every time
                instructions=persona.instructions(customer, now or persona.local_now(s.timezone)),
                input=query,
                conversation=conversation_id,
                max_output_tokens=s.max_output_tokens,
                text={"format": REPLY_FORMAT},
                **kwargs,
            )
        except openai.OpenAIError as exc:
            logger.warning("OpenAI request failed (%s)", _describe(exc))
            raise AssistantError(f"OpenAI request failed ({_describe(exc)})") from None
        raw = (response.output_text or "").strip()
        if not raw:
            logger.warning("OpenAI returned no text (status %s)", getattr(response, "status", "?"))
            raise AssistantError("OpenAI returned no text")
        answer, is_order, order_id = parse_reply(raw)
        if not answer:
            raise AssistantError("OpenAI returned no answer text")
        return Reply(text=answer, conversation_id=conversation_id, is_order=is_order, order_id=order_id)
