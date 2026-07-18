# Avow — OpenRouter client polish + retry-config guard — design

Small hardening batch from the LLM-resilience review's minor findings. Three independent, bounded
changes; no behavior change for the happy path.

## 1. Connection reuse (pooling)

Today `OpenRouterClient._post` uses the module-level `httpx.post(...)` when no `http_client` was
injected, opening a fresh TLS connection per call. Over a long verification run (K references per
gauntlet, many gauntlets) that is repeated handshake latency.

Change: in `__init__`, when `http_client is None`, construct and hold one `httpx.Client(timeout=timeout)`
as `self._http`. `_post` then always calls `self._http.post(...)` (the injected-fake test path is
unchanged — a fake with `.post` is still used as-is). Add `close()` and `__enter__`/`__exit__` so the
pooled client is releasable; the SDK-style usage (construct, use for a run, process exits) does not
require explicit close, but a context manager makes leak-free use easy and testable.

## 2. `_extract_json` robustness

Today `_extract_json` strips a leading ```` ```json ```` fence only. Models that emit reasoning text
before the JSON, or trailing prose after it, are not handled and fail the parse (then the existing
one-shot "reply with only JSON" correction fires, wasting a round-trip).

Change: after fence-stripping, if the content does not start with `{`, slice the outermost object with
`first "{"` to `last "}"` (structured-output responses are a single object, so first-open to last-close
is a safe, string-brace-agnostic heuristic — no fragile brace counting). Return the whole string
unchanged when no `{` is present (let the caller's validation raise its normal error).

## 3. `llm_max_retries` config guard

`RunConfig.llm_max_retries` flows into `anthropic.Anthropic(max_retries=...)`, which requires `>= 0`.
Add a validator (matching the existing `graveyard_patterns_k` / `adjudicate_references_k` style) that
rejects a negative value with a clear message, rather than surfacing an opaque SDK error at client
construction.

## Honesty / scope

None of this changes a verdict or a confidence number; it is latency, parse-robustness, and
input-validation polish. The OpenRouter path remains offline-verified only (no live OpenRouter run),
unchanged by this batch.

## Testing

- **1:** a default `OpenRouterClient()` holds a reusable `httpx.Client` (its `_http` is not None and is
  reused across two `_post` calls via a monkeypatched transport that counts connections, or simplest:
  assert `client._http` is a single stable object across calls); `close()` and the context manager
  release it.
- **2:** `_extract_json` returns the object for: a bare object; a fenced object; reasoning-then-object
  (`"Let me think... {\"a\": 1}"`); object-then-trailing-prose; and returns the input unchanged when
  there is no `{`.
- **3:** `RunConfig(llm_max_retries=-1)` raises `ValueError`; `llm_max_retries=0` is allowed (0 means the
  SDK does no retries, a valid choice).

## Out of scope

- Embedding/semantic relevance retrieval (a separate feature with its own design cycle).
- A cross-process graveyard lock (Unix-only `flock` would break the Windows portability requirement;
  duplicates are harmless and already documented — not worth breaking portability).
