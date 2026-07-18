from types import SimpleNamespace

import pytest

from avow.openrouter import OpenRouterClient
from avow.backtranslation import IntentMatch


class FakeHTTP:
    """Stands in for httpx — records the request, returns a canned OpenRouter response."""
    def __init__(self, content, usage, status=200):
        self.content = content
        self.usage = usage
        self.status = status
        self.last = None

    def post(self, url, headers, json, timeout):
        self.last = {"url": url, "headers": headers, "json": json, "timeout": timeout}
        return SimpleNamespace(
            status_code=self.status,
            text="error body",
            json=lambda: {"choices": [{"message": {"content": self.content}}], "usage": self.usage},
        )


def _client(content, usage, status=200):
    return OpenRouterClient(api_key="k", http_client=FakeHTTP(content, usage, status))


def test_parses_json_into_pydantic_and_maps_usage():
    c = _client('{"score": 0.9, "divergences": ["a", "b"]}',
                {"prompt_tokens": 12, "completion_tokens": 7})
    resp = c.messages.parse(model="google/gemini-2.5-flash", max_tokens=100,
                            messages=[{"role": "user", "content": "judge this"}],
                            output_format=IntentMatch)
    assert isinstance(resp.parsed_output, IntentMatch)
    assert resp.parsed_output.score == 0.9 and resp.parsed_output.divergences == ["a", "b"]
    assert resp.usage.input_tokens == 12 and resp.usage.output_tokens == 7
    sent = c.messages._client._http.last["json"]
    assert sent["model"] == "google/gemini-2.5-flash"          # routes to the requested model
    response_format = sent["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["name"] == "IntentMatch"
    assert response_format["json_schema"]["strict"] is True
    assert "score" in response_format["json_schema"]["schema"]["properties"]
    assert "score" in sent["messages"][0]["content"]            # the schema was injected (system msg)
    assert sent["messages"][1]["content"] == "judge this"       # the caller's prompt preserved
    assert c.messages._client._http.last["timeout"] == 120


def test_strips_code_fences():
    c = _client('```json\n{"score": 0.5, "divergences": []}\n```',
                {"prompt_tokens": 1, "completion_tokens": 1})
    resp = c.messages.parse(model="m", messages=[{"role": "user", "content": "x"}],
                            output_format=IntentMatch)
    assert resp.parsed_output.score == 0.5


def test_non_200_raises():
    c = _client("ignored", {}, status=402)
    try:
        c.messages.parse(model="m", messages=[{"role": "user", "content": "x"}], output_format=IntentMatch)
        raised = False
    except RuntimeError:
        raised = True
    assert raised


def test_missing_api_key_fails_before_request(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    c = OpenRouterClient(http_client=FakeHTTP("{}", {}))
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        c.messages.parse(model="m", messages=[], output_format=IntentMatch)


class SequenceHTTP:
    def __init__(self):
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append(json)
        content = (
            "not json" if len(self.calls) == 1
            else '{"score": 0.8, "divergences": []}'
        )
        usage = {"prompt_tokens": 2, "completion_tokens": 3}
        return SimpleNamespace(status_code=200, text="", json=lambda: {
            "choices": [{"message": {"content": content}}], "usage": usage,
        })


def test_retry_includes_rejected_reply_and_accounts_for_both_attempts():
    http = SequenceHTTP()
    c = OpenRouterClient(api_key="k", http_client=http)
    resp = c.messages.parse(model="m", messages=[], output_format=IntentMatch)
    assert resp.parsed_output.score == 0.8
    assert (resp.usage.input_tokens, resp.usage.output_tokens) == (4, 6)
    retry_messages = http.calls[1]["messages"]
    assert retry_messages[-2] == {"role": "assistant", "content": "not json"}
    assert "previous reply" in retry_messages[-1]["content"]


def test_malformed_success_response_has_actionable_error():
    class BadHTTP:
        def post(self, *_args, **_kwargs):
            return SimpleNamespace(status_code=200, text="", json=lambda: {"choices": []})

    c = OpenRouterClient(api_key="k", http_client=BadHTTP())
    with pytest.raises(RuntimeError, match="malformed chat-completion"):
        c.messages.parse(model="m", messages=[], output_format=IntentMatch)
