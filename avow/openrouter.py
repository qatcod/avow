"""Cross-provider client adapter, backed by OpenRouter (OpenAI-compatible).

Exposes the same `.messages.parse(model=, max_tokens=, messages=, output_format=)`
-> response with `.parsed_output` + `.usage.input_tokens/output_tokens` interface that
Avow's injectable clients (Examiner / panel / oracle / ideator / supervisor) expect,
so a single OpenRouterClient can route to any OpenRouter model that supports structured
outputs. The existing cross-model panel becomes a true cross-provider panel by injecting
this client and setting `panel_models` to e.g.
``["google/gemini-2.5-flash", "moonshotai/kimi-k2.5", "deepseek/deepseek-chat-v3.1"]``.

Structured output is provider-agnostic: the target Pydantic JSON Schema is sent through
OpenRouter's strict `json_schema` response format and repeated in a system instruction,
then the response is validated into the model (with one retry on a malformed reply).
Usage maps OpenRouter's prompt_tokens/completion_tokens onto input_tokens/output_tokens.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass
class _Usage:
    input_tokens: int
    output_tokens: int


@dataclass
class _ParsedResponse:
    parsed_output: object
    usage: _Usage


def _extract_json(content: str) -> str:
    s = (content or "").strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s[3:]
        if s.lower().startswith("json"):
            s = s[4:]
    return s.strip()


class _Messages:
    def __init__(self, client: "OpenRouterClient") -> None:
        self._client = client

    def parse(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        output_format,
        max_tokens: int = 4000,
        **_ignored,
    ) -> _ParsedResponse:
        schema = output_format.model_json_schema()
        schema_name = getattr(output_format, "__name__", "structured_response")
        instruction = (
            "Respond with ONLY a single JSON object that conforms to this JSON Schema. "
            "No markdown, no code fences, no prose:\n" + json.dumps(schema)
        )
        base_messages = [{"role": "system", "content": instruction}] + list(messages)

        last_error: Exception | None = None
        attempt_messages = base_messages
        input_tokens = 0
        output_tokens = 0
        for _ in range(2):  # one retry on malformed JSON / validation miss
            data = self._client._post({
                "model": model,
                "messages": attempt_messages,
                "max_tokens": max_tokens,
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "strict": True,
                        "schema": schema,
                    },
                },
            })
            try:
                content = data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError("OpenRouter returned a malformed chat-completion response") from exc
            if not isinstance(content, str):
                raise RuntimeError("OpenRouter returned non-text chat-completion content")
            usage = data.get("usage") or {}
            input_tokens += _token_count(usage, "prompt_tokens")
            output_tokens += _token_count(usage, "completion_tokens")
            try:
                parsed = output_format.model_validate_json(_extract_json(content))
                return _ParsedResponse(
                    parsed_output=parsed,
                    usage=_Usage(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    ),
                )
            except Exception as exc:  # noqa: BLE001 - retry once, then surface
                last_error = exc
                # Include the rejected answer so the corrective message has real
                # conversational context instead of referring to an unseen reply.
                attempt_messages = base_messages + [
                    {"role": "assistant", "content": content},
                    {"role": "user",
                     "content": "Your previous reply was not valid JSON for the schema. "
                                "Reply with ONLY the JSON object."}
                ]
        raise ValueError(
            f"OpenRouter response did not validate as {schema_name}: {last_error}"
        )


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, base_url: str = _BASE_URL,
                 timeout: float = 120, http_client=None) -> None:
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._http = http_client  # injectable for offline tests
        self.messages = _Messages(self)

    def _post(self, body: dict) -> dict:
        if not self.api_key:
            raise ValueError(
                "OpenRouter API key is required; pass api_key= or set OPENROUTER_API_KEY"
            )
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        url = self.base_url + "/chat/completions"
        if self._http is not None:
            resp = self._http.post(url, headers=headers, json=body, timeout=self.timeout)
        else:
            resp = httpx.post(url, headers=headers, json=body, timeout=self.timeout)
        if not 200 <= resp.status_code < 300:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:300]}")
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError("OpenRouter returned a non-JSON response") from exc
        if not isinstance(data, dict):
            raise RuntimeError("OpenRouter returned a non-object JSON response")
        return data


def _token_count(usage: object, key: str) -> int:
    """Read a non-negative integer usage field without letting bad metadata break parsing."""
    if not isinstance(usage, dict):
        return 0
    try:
        return max(0, int(usage.get(key, 0)))
    except (TypeError, ValueError):
        return 0
