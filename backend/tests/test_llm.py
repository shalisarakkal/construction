import json
from urllib.error import URLError

from app import llm
from app.config import settings


class _FakeResponse:
    """Minimal stand-in for the context-manager urllib.request.urlopen
    returns, wrapping a JSON body."""

    def __init__(self, body: bytes):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


# ---------------------------------------------------------------------------
# is_configured()
# ---------------------------------------------------------------------------


def test_is_configured_anthropic_true_with_api_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-ant-test")

    assert llm.is_configured() is True


def test_is_configured_anthropic_false_without_api_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", None)

    assert llm.is_configured() is False


def test_is_configured_ollama_true_when_reachable(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=None: _FakeResponse(b"{}"))

    assert llm.is_configured() is True


def test_is_configured_ollama_false_when_unreachable(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")

    def raise_url_error(url, timeout=None):
        raise URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    assert llm.is_configured() is False


# ---------------------------------------------------------------------------
# synthesize_answer() / synthesize_summary() provider branching
# ---------------------------------------------------------------------------


def test_synthesize_answer_routes_to_ollama(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    captured = {}
    monkeypatch.setattr(
        llm, "_ollama_chat",
        lambda system, user_content: captured.update(system=system, user_content=user_content) or "ollama answer",
    )

    result = llm.synthesize_answer("What is required?", "Context block text")

    assert result == "ollama answer"
    assert captured["system"] == llm.SYSTEM_PROMPT
    assert "Context block text" in captured["user_content"]
    assert "What is required?" in captured["user_content"]


def test_synthesize_answer_routes_to_anthropic(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    captured = {}
    monkeypatch.setattr(
        llm, "_anthropic_chat",
        lambda system, user_content: captured.update(system=system) or "anthropic answer",
    )

    result = llm.synthesize_answer("q", "ctx")

    assert result == "anthropic answer"
    assert captured["system"] == llm.SYSTEM_PROMPT


def test_synthesize_summary_routes_to_ollama_with_summary_prompt(monkeypatch):
    monkeypatch.setattr(settings, "llm_provider", "ollama")
    captured = {}
    monkeypatch.setattr(
        llm, "_ollama_chat",
        lambda system, user_content: captured.update(system=system, user_content=user_content) or "ollama summary",
    )

    result = llm.synthesize_summary("njac_5_23_1.pdf", "Chunk text here")

    assert result == "ollama summary"
    assert captured["system"] == llm.SUMMARY_SYSTEM_PROMPT
    assert captured["user_content"] == "Document: njac_5_23_1.pdf\n\nContext:\nChunk text here"


# ---------------------------------------------------------------------------
# _anthropic_chat()
# ---------------------------------------------------------------------------


def test_anthropic_chat_extracts_and_joins_text_blocks(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    monkeypatch.setattr(settings, "anthropic_model", "claude-sonnet-5")

    captured = {}

    class FakeBlock:
        def __init__(self, type_, text=""):
            self.type = type_
            self.text = text

    class FakeResponse:
        content = [FakeBlock("text", "Hello "), FakeBlock("text", "world"), FakeBlock("tool_use")]

    class FakeMessages:
        def create(self, **kwargs):
            captured.update(kwargs)
            return FakeResponse()

    class FakeAnthropic:
        def __init__(self, api_key):
            captured["api_key"] = api_key
            self.messages = FakeMessages()

    monkeypatch.setattr("anthropic.Anthropic", FakeAnthropic)

    result = llm._anthropic_chat("system prompt", "user content")

    # Non-text blocks (e.g. tool_use) are filtered out of the joined result.
    assert result == "Hello world"
    assert captured["api_key"] == "sk-test"
    assert captured["model"] == "claude-sonnet-5"
    assert captured["max_tokens"] == 1024
    assert captured["system"] == "system prompt"
    assert captured["messages"] == [{"role": "user", "content": "user content"}]


# ---------------------------------------------------------------------------
# _ollama_chat()
# ---------------------------------------------------------------------------


def test_ollama_chat_includes_num_gpu_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ollama_num_gpu", 0)
    monkeypatch.setattr(settings, "ollama_model", "llama3.1:8b")
    monkeypatch.setattr(settings, "ollama_base_url", "http://localhost:11434")

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        captured["timeout"] = timeout
        return _FakeResponse(json.dumps({"message": {"content": "hello"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = llm._ollama_chat("system prompt", "user content")

    assert result == "hello"
    payload = json.loads(captured["req"].data)
    assert payload["model"] == "llama3.1:8b"
    assert payload["options"] == {"num_predict": 1024, "num_gpu": 0}
    assert payload["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user content"},
    ]
    assert captured["req"].full_url == "http://localhost:11434/api/chat"
    assert captured["timeout"] == 300


def test_ollama_chat_omits_num_gpu_when_unset(monkeypatch):
    monkeypatch.setattr(settings, "ollama_num_gpu", None)

    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["req"] = req
        return _FakeResponse(json.dumps({"message": {"content": "hi"}}).encode())

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    llm._ollama_chat("system prompt", "user content")

    payload = json.loads(captured["req"].data)
    assert payload["options"] == {"num_predict": 1024}
