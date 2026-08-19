import pytest
from weaver.agent.text_refine import refine, TextRefinementError

def test_refine_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(TextRefinementError, match="OPENAI_API_KEY"):
        refine("return x;", api_key=None)

def test_refine_returns_model_text(monkeypatch):
    class FakeResponse:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": "return x + 1;"}}]}
    def fake_post(url, headers, json, timeout):
        assert headers["Authorization"] == "Bearer sk-test"
        assert "gpt-4o-mini" in str(json)
        return FakeResponse()
    monkeypatch.setattr("weaver.agent.text_refine.requests.post", fake_post)
    result = refine("return x;", api_key="sk-test")
    assert result == "return x + 1;"

def test_refine_raises_on_http_error(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "server error"
    monkeypatch.setattr("weaver.agent.text_refine.requests.post",
                         lambda *a, **k: FakeResponse())
    with pytest.raises(TextRefinementError, match="500"):
        refine("return x;", api_key="sk-test")
