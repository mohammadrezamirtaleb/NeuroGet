"""Regression coverage for credentials, full-document retrieval and history."""
from types import SimpleNamespace
from unittest.mock import Mock

from app.services.ai_client import AIClient
from app.services.document_context import retrieve_context, normalize_history
from app.services.content_analyzer import ContentAnalyzer


def test_global_credentials_are_never_used_for_a_new_provider(monkeypatch):
    import app.services.ai_client as module
    values = {
        "ai_provider": "Anthropic (Claude)", "ai_api_key": "legacy-other-provider-key",
        "ai_api_key:OpenAI (GPT-4o-mini)": "openai-only", "ai_model": "other-provider-model"
    }
    monkeypatch.setattr(module, "get_setting", lambda key, default=None: values.get(key, default))
    assert AIClient.get_api_key() == ""
    assert AIClient.get_model_name() == ""
    assert AIClient.get_api_key("OpenAI (GPT-4o-mini)") == "openai-only"
    post = Mock()
    monkeypatch.setattr(module.requests, "post", post)
    monkeypatch.setattr(AIClient, "_offline_providers", {})
    assert AIClient.call_llm("hello") is None
    post.assert_not_called()


def test_provider_switch_cannot_mix_endpoint_and_key(monkeypatch):
    import app.services.ai_client as module
    settings = {"ai_api_key:OpenAI": "openai-only", "ai_api_key:OpenRouter": "router-only"}
    monkeypatch.setattr(module, "get_setting", lambda key, default=None: settings.get(key, default))
    configured = Mock(side_effect=["OpenAI", "OpenRouter"])
    monkeypatch.setattr(AIClient, "get_configured_provider", configured)
    monkeypatch.setattr(AIClient, "_offline_providers", {})
    post = Mock(return_value=SimpleNamespace(
        status_code=200, json=lambda: {"choices": [{"message": {"content": "ok"}}]}
    ))
    monkeypatch.setattr(module.requests, "post", post)
    assert AIClient.call_llm("hello") == "ok"
    configured.assert_called_once()
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer openai-only"
    assert post.call_args.args[0].startswith("https://api.openai.com/")


def test_document_qa_retrieves_facts_after_first_5000_characters(monkeypatch):
    fact = "Aurora deployment deadline is 17 November."
    document = "Ordinary introductory material.\n" * 500 + fact
    llm = Mock(return_value="17 November")
    monkeypatch.setattr(AIClient, "call_llm", llm)
    assert AIClient.chat_with_document(document, "What is Aurora's deployment deadline?") == "17 November"
    assert fact in llm.call_args.args[0]


def test_document_qa_searches_file_beyond_summary_limit(monkeypatch, tmp_path):
    fact = "Aurora deployment deadline is 17 November."
    path = tmp_path / "long.txt"
    path.write_text("Unrelated introduction.\n" * 6000 + fact, encoding="utf-8")
    monkeypatch.setattr(AIClient, "call_llm", lambda *_a, **_k: None)
    reply = AIClient.chat_with_document("short summary", "Aurora deployment deadline?", filepath=str(path))
    assert fact in reply


def test_follow_up_receives_history_and_relevant_document_facts(monkeypatch):
    history = [{"role": "user", "content": "Tell me about Project Aurora."},
               {"role": "assistant", "content": "Aurora is a satellite deployment."}]
    llm = Mock(return_value="17 November")
    monkeypatch.setattr(AIClient, "call_llm", llm)
    AIClient.chat_with_document(
        "Introduction.\n" * 2000 + "Aurora deployment deadline is 17 November.",
        "When is its deadline?", history
    )
    prompt = llm.call_args.args[0]
    assert "user: Tell me about Project Aurora." in prompt
    assert "assistant: Aurora is a satellite deployment." in prompt
    assert "17 November" in prompt


def test_context_and_history_remain_bounded():
    text = "Document explanation.\n" * 100000 + "Aurora deadline is November."
    history = [{"role": "user", "content": "Aurora " * 10000}] * 30
    context = retrieve_context(text, "What is the Aurora deadline?", history)
    assert len(context) <= 6000
    assert "Aurora deadline is November." in context
    normalized = normalize_history(history)
    assert len(normalized) <= 6
    assert all(len(message["content"]) <= 800 for message in normalized)


def test_pdf_retrieval_reads_pages_after_page_20(monkeypatch, tmp_path):
    import pypdf
    pages = [SimpleNamespace(extract_text=lambda: "Introduction") for _ in range(29)]
    pages.append(SimpleNamespace(extract_text=lambda: "Aurora deadline is November."))
    monkeypatch.setattr(pypdf, "PdfReader", lambda _document: SimpleNamespace(pages=pages))
    path = tmp_path / "long.pdf"
    path.write_bytes(b"test PDF reader fixture")
    text = "".join(ContentAnalyzer.iter_document_text(str(path)))
    assert "--- Page 30 ---" in text
    assert "Aurora deadline is November." in retrieve_context("", "Aurora deadline?", filepath=str(path))


def test_multilingual_passages_are_retrieved():
    fact = "مهلت پروژه آفتاب روز شنبه است."
    text = "Unrelated introduction.\n" * 1000 + fact
    assert fact in retrieve_context(text, "مهلت پروژه آفتاب چیست؟")


def test_unreadable_document_produces_a_clear_response(monkeypatch, tmp_path):
    llm = Mock()
    monkeypatch.setattr(AIClient, "call_llm", llm)
    reply = AIClient.chat_with_document("", "deadline?", filepath=str(tmp_path / "missing.txt"))
    assert "could not be read" in reply
    llm.assert_not_called()


def test_utf16_document_is_searchable(monkeypatch, tmp_path):
    path = tmp_path / "unicode.txt"
    fact = "مهلت پروژه آفتاب روز شنبه است."
    path.write_text("Introduction.\n" * 1000 + fact, encoding="utf-16")
    monkeypatch.setattr(AIClient, "call_llm", lambda *_a, **_k: None)
    assert fact in AIClient.chat_with_document("", "مهلت پروژه آفتاب چیست؟", filepath=str(path))


def test_empty_document_is_not_replaced_with_summary_metadata(monkeypatch, tmp_path):
    path = tmp_path / "empty.txt"
    path.write_text("", encoding="utf-8")
    llm = Mock()
    monkeypatch.setattr(AIClient, "call_llm", llm)
    reply = AIClient.chat_with_document("Summary metadata", "What does it say?", filepath=str(path))
    assert "no extractable document text" in reply
    llm.assert_not_called()
