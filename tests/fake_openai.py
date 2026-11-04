"""An in-process OpenAI: answers the few endpoints the app uses, and records what it was sent."""

from __future__ import annotations

import json
import re

import httpx
import openai

BASE = "https://openai.example.test/v1"
API_KEY = "demo-openai-key"


def structured(answer: str, *, is_order: bool = False, order_id: str = "") -> str:
    """What the model returns when it follows the persona: the JSON with is_order, order_id and answer."""
    return json.dumps({"is_order": is_order, "order_id": order_id, "answer": answer})


def _json(status: int, body: dict) -> httpx.Response:
    return httpx.Response(status, json=body)


class FakeOpenAI:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        # Each is the text the model returns: structured() normally, anything else to test the fallback
        self.answers: list[str] = [structured("Good morning, Jane! How can I help?")]
        self.fail: dict[str, int] = {}  # route name -> HTTP status to answer with
        self.empty_output = False
        self.file_status = "completed"
        self.uploaded: list[str] = []
        self._conversations = 0
        self._answered = 0

    # -- helpers for the tests
    def client(self) -> openai.OpenAI:
        return openai.OpenAI(
            api_key=API_KEY,
            base_url=BASE,
            http_client=httpx.Client(transport=httpx.MockTransport(self.handle)),
            max_retries=0,
        )

    def calls(self, route: str) -> list[httpx.Request]:
        return [r for r in self.requests if self._route(r) == route]

    def body(self, route: str, index: int = -1) -> dict:
        return json.loads(self.calls(route)[index].content)

    # -- the server
    @staticmethod
    def _route(request: httpx.Request) -> str:
        path = request.url.path.removeprefix("/v1")
        if request.method == "POST" and path == "/conversations":
            return "conversations"
        if request.method == "POST" and path == "/responses":
            return "responses"
        if request.method == "POST" and path == "/vector_stores":
            return "vector_stores"
        if request.method == "POST" and path == "/files":
            return "files"
        if request.method == "POST" and re.fullmatch(r"/vector_stores/[^/]+/files", path):
            return "vector_store_files"
        if request.method == "GET" and re.fullmatch(r"/vector_stores/[^/]+/files/[^/]+", path):
            return "vector_store_file_poll"
        return "unknown"

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        route = self._route(request)
        if request.headers.get("authorization") != f"Bearer {API_KEY}":
            return _json(401, {"error": {"message": f"Incorrect API key provided: {API_KEY}", "type": "x"}})
        if route in self.fail:
            return _json(
                self.fail[route],
                {
                    "error": {
                        "message": "SECRET detail with key " + API_KEY,
                        "type": "server_error",
                        "code": None,
                    }
                },
            )
        if route == "conversations":
            self._conversations += 1
            return _json(
                200, {"id": f"conv_{self._conversations}", "object": "conversation", "created_at": 0}
            )
        if route == "responses":
            text = self.answers[min(self._answered, len(self.answers) - 1)]
            self._answered += 1
            content = [] if self.empty_output else [{"type": "output_text", "text": text, "annotations": []}]
            return _json(
                200,
                {
                    "id": f"resp_{self._answered}",
                    "object": "response",
                    "created_at": 0,
                    "status": "completed",
                    "model": "demo-model",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "content": content,
                        }
                    ],
                },
            )
        if route == "vector_stores":
            return _json(
                200,
                {
                    "id": "vs_demo1",
                    "object": "vector_store",
                    "name": "n",
                    "status": "completed",
                    "created_at": 0,
                },
            )
        if route == "files":
            name = re.search(rb'filename="([^"]+)"', request.content)
            self.uploaded.append(name.group(1).decode() if name else "?")
            return _json(
                200,
                {
                    "id": f"file-{len(self.uploaded)}",
                    "object": "file",
                    "bytes": 1,
                    "created_at": 0,
                    "filename": self.uploaded[-1],
                    "purpose": "assistants",
                },
            )
        if route == "vector_store_files":
            return _json(200, self._vector_file(json.loads(request.content)["file_id"], "in_progress"))
        if route == "vector_store_file_poll":
            return _json(200, self._vector_file(request.url.path.rsplit("/", 1)[1], self.file_status))
        return _json(404, {"error": {"message": "no such route", "type": "invalid_request_error"}})

    def _vector_file(self, file_id: str, status: str) -> dict:
        body = {
            "id": file_id,
            "object": "vector_store.file",
            "vector_store_id": "vs_demo1",
            "status": status,
            "created_at": 0,
            "usage_bytes": 0,
        }
        if status == "failed":
            body["last_error"] = {"code": "unsupported_file", "message": "SECRET detail"}
        return body
