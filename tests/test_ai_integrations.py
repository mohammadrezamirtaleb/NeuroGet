"""Provider, routing, and link validation regressions without external services."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests

from app.services.ai_client import AIClient
from app.services.router import SmartRouter


@pytest.fixture(autouse=True)
def configured_provider(monkeypatch):
    monkeypatch.setattr(AIClient, "_offline_providers", {})
    monkeypatch.setattr(AIClient, "get_api_key", lambda provider=None: "test-provider-key")
    monkeypatch.setattr(AIClient, "get_model_name", lambda provider=None: "")


def json_response(payload):
    return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)


def test_claude_uses_messages_api(monkeypatch):
    monkeypatch.setattr(AIClient, "get_configured_provider", lambda: "Anthropic (Claude)")
    post = Mock(return_value=json_response({"content": [{"type": "text", "text": "Documents"}]}))
    monkeypatch.setattr(requests, "post", post)
    assert AIClient.call_llm("classify", system_prompt="system", max_tokens=40) == "Documents"
    args, kwargs = post.call_args
    assert args[0] == "https://api.anthropic.com/v1/messages"
    assert kwargs["headers"]["x-api-key"] == "test-provider-key"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"
    assert kwargs["json"]["system"] == "system"
    assert kwargs["json"]["messages"] == [{"role": "user", "content": "classify"}]


@pytest.mark.parametrize("model,path,payload", [
    ("glm-5.1", "/openai/v1/chat/completions", {"choices": [{"message": {"content": "ok"}}]}),
    ("gpt-5.5", "/openai/v1/responses", {"output": [{"content": [{"type": "output_text", "text": "ok"}]}]}),
    ("claude-sonnet-4-6", "/anthropic/v1/messages", {"content": [{"type": "text", "text": "ok"}]}),
    ("gemini-3.1-pro", "/google/v1beta/models/gemini-3.1-pro:generateContent", {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]})
])
def test_opencode_uses_its_own_api_family(monkeypatch, model, path, payload):
    monkeypatch.setattr(AIClient, "get_configured_provider", lambda: "OpenCode Zen")
    monkeypatch.setattr(AIClient, "get_model_name", lambda provider=None: model)
    post = Mock(return_value=json_response(payload))
    monkeypatch.setattr(requests, "post", post)
    assert AIClient.call_llm("hello") == "ok"
    assert post.call_args.args[0] == "https://opencode.ai/inference" + path


def test_copilot_never_sends_tokens_to_openai(monkeypatch):
    monkeypatch.setattr(AIClient, "get_configured_provider", lambda: "GitHub Copilot")
    post = Mock()
    monkeypatch.setattr(requests, "post", post)
    assert AIClient.call_llm("hello") is None
    post.assert_not_called()


class LinkResponse:
    def __init__(self, mime, body):
        self.status_code = 200
        self.headers = {"Content-Type": mime}
        self.body = body
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def raise_for_status(self):
        pass

    def iter_content(self, _size):
        yield self.body


@pytest.mark.parametrize("mime,body", [
    ("text/html; charset=utf-8", b"<!DOCTYPE html>"),
    ("application/octet-stream", b"<html><body>sign in</body></html>"),
    ("application/json", b'{"error":"unauthorized"}')
])
def test_webpages_are_not_offered_as_downloads(monkeypatch, mime, body):
    response = LinkResponse(mime, body)
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    result = AIClient._validate_download_result({
        "official_url": "https://vendor.test/download", "direct_link_hint": "https://vendor.test/latest"
    })
    assert not result["direct_link_hint"]
    assert result["official_url"] == "https://vendor.test/download"
    assert response.closed


def test_binary_download_link_is_retained(monkeypatch):
    response = LinkResponse("application/octet-stream", b"MZbinary")
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    url = "https://vendor.test/installer.exe"
    assert AIClient._validate_download_result({"direct_link_hint": url})["direct_link_hint"] == url
    assert response.closed


def test_invalid_ai_link_is_not_requested(monkeypatch):
    get = Mock()
    monkeypatch.setattr(requests, "get", get)
    assert not AIClient._validate_download_result({"direct_link_hint": ["bad"]})["direct_link_hint"]
    get.assert_not_called()


def test_routing_uses_selected_provider_once(monkeypatch, tmp_path):
    import app.services.router as module
    monkeypatch.setattr(module, "get_setting", lambda _key, default: default)
    rule = SimpleNamespace(condition_type="ai_category", condition_value="Education / Course",
                           destination_path=str(tmp_path / "Lessons"), is_active=1)
    monkeypatch.setattr(module, "get_all_rules", lambda: [rule])
    classify = Mock(return_value="Games")
    monkeypatch.setattr(AIClient, "classify_category", classify)
    dest, category = SmartRouter.route_download("https://vendor.test/file", "file.bin", str(tmp_path))
    assert category == "Games"
    assert dest == str(tmp_path / "Games")
    classify.assert_called_once_with("file.bin", "https://vendor.test/file", ".bin")


def test_routing_keeps_explicit_extension_rules(monkeypatch, tmp_path):
    import app.services.router as module
    monkeypatch.setattr(module, "get_setting", lambda _key, default: default)
    rule = SimpleNamespace(condition_type="ext", condition_value=".pdf", name="Books",
                           destination_path=str(tmp_path / "Books"), is_active=1)
    monkeypatch.setattr(module, "get_all_rules", lambda: [rule])
    classify = Mock()
    monkeypatch.setattr(AIClient, "classify_category", classify)
    assert SmartRouter.route_download("https://vendor.test/book.pdf", "book.pdf", str(tmp_path))[1] == "Books"
    classify.assert_not_called()
