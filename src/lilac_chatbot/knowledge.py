"""The knowledge base: a vector store the assistant searches with ``file_search``.

``create_assistant.py`` uploaded ``reference.pdf`` and gave its id to the old assistant's ``retrieval`` tool.
The same file is uploaded to a vector store now, once, by ``lilac-chatbot init-knowledge``; the store's id
goes in ``VECTOR_STORE_ID``. The old LangChain code also put every Shopify customer and order into a vector
store; only the product catalogue is uploaded now (see ``shopify.py``).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

import openai

logger = logging.getLogger(__name__)

STORE_NAME = "Life in Lilac support knowledge"


class KnowledgeError(Exception):
    """The knowledge base could not be built. The message holds no OpenAI error text."""


def _failure(exc: openai.OpenAIError) -> str:
    status = getattr(exc, "status_code", None)
    return type(exc).__name__ + (f", HTTP {status}" if status else "")


def create_knowledge_base(
    client: openai.OpenAI, files: Sequence[Path | tuple[str, bytes]], *, name: str = STORE_NAME
) -> str:
    """Create a vector store holding `files` and return its id.

    A file is a path, or a ``(file name, content)`` pair. Every file must finish indexing: a file OpenAI
    could not process stops the job (the store is left behind, to be deleted in the OpenAI dashboard).
    """
    if not files:
        raise KnowledgeError("There is nothing to upload")
    try:
        store = client.vector_stores.create(name=name)
        for item in files:
            label = item.name if isinstance(item, Path) else item[0]
            uploaded = client.vector_stores.files.upload_and_poll(vector_store_id=store.id, file=item)
            if uploaded.status != "completed":
                code = getattr(getattr(uploaded, "last_error", None), "code", None)
                raise KnowledgeError(
                    f"OpenAI could not index {label} (status {uploaded.status}"
                    + (f", {code}" if code else "")
                    + ")"
                )
            logger.info("Indexed %s", label)
    except openai.OpenAIError as exc:
        raise KnowledgeError(f"OpenAI request failed ({_failure(exc)})") from None
    return store.id
