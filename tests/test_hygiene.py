"""Things that went wrong in the first version and must not come back."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "lilac_chatbot"


def git_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"],  # noqa: S607
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return [p for p in out.split("\0") if p]


def tracked_text_files():
    names = [
        p
        for p in git_files()
        if p.endswith((".py", ".html", ".md", ".toml", ".yml", ".example", ".css", ".js"))
    ]
    files = [ROOT / p for p in names if p != "uv.lock"]
    return [f for f in files if f.exists()] or [f for f in ROOT.rglob("*.py") if ".venv" not in f.parts]


def test_no_credentials_in_the_tree():
    patterns = {
        "an OpenAI key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
        "a Shopify access token": re.compile(r"\bshp(at|ca|pa|ss)_[A-Za-z0-9]{16,}"),
        "an AWS access key id": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
        "a Google API key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
        "a long literal assigned to a key/secret/token name": re.compile(
            r"""(?i)(api_?key|secret|token|passw\w*)\w*\s*[=:]\s*['"][A-Za-z0-9_/+-]{20,}['"]"""
        ),
    }
    found = []
    for f in tracked_text_files():
        if f.name == "test_hygiene.py":
            continue
        text = f.read_text(errors="ignore")
        found += [f"{f.relative_to(ROOT)}: {label}" for label, p in patterns.items() if p.search(text)]
    assert found == []


def test_no_database_env_file_or_vector_store_is_tracked():
    def is_local_state(path: str) -> bool:
        return (
            path.endswith((".db", ".sqlite3"))
            or path.split("/")[-1] == ".env"
            or path.startswith(("instance/", "data/chroma"))
            or "file::memory" in path
        )

    bad = [p for p in git_files() if is_local_state(p)]
    assert bad == []


def test_the_server_is_never_started_in_debug_mode():
    for f in SRC.rglob("*.py"):
        assert "debug=True" not in f.read_text(), f.name


def test_no_unbounded_http_calls_and_no_blocking_requests_library():
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        assert "requests." not in text and "import requests" not in text, f.name
    assert "httpx.Client(timeout=settings.request_timeout)" in (SRC / "shopify.py").read_text()
    assert "timeout=settings.request_timeout" in (SRC / "assistant.py").read_text()


def test_the_retired_assistants_api_is_not_used():
    """It was shut down on 2026-08-26; the first version was built on beta.assistants and beta.threads."""
    for f in SRC.rglob("*.py"):
        text = f.read_text()
        assert "beta.assistants" not in text and "beta.threads" not in text and '"retrieval"' not in text, (
            f.name
        )


def test_the_persona_is_defined_once():
    """Five files had their own copy of the instructions and the part-of-day rule."""
    hits = [f.name for f in SRC.rglob("*.py") if "Good morning" in f.read_text()]
    assert hits == ["persona.py"]


def test_env_example_lists_every_variable_the_settings_read():
    source = (SRC / "config.py").read_text()
    read = set(re.findall(r"""(?:get|_number)\(\s*(?:environ,\s*)?["']([A-Z][A-Z0-9_]+)["']""", source))
    documented = set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", (ROOT / ".env.example").read_text(), re.M))
    assert {
        "OPENAI_API_KEY",
        "SECRET_KEY",
        "VECTOR_STORE_ID",
        "SHOPIFY_ACCESS_TOKEN",
        "CHAT_PAUSE_SECONDS",
    } <= read
    assert sorted(read - documented) == []
