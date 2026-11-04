"""Jessica, the Life in Lilac support assistant: OpenAI Responses API, file search and a small Flask app."""

from .app import create_app

__all__ = ["__version__", "create_app"]
__version__ = "0.1.0"
