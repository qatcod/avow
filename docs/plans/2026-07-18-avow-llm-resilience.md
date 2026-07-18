# LLM Resilience (long runs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make long multi-call LLM runs survive transient network failures: higher Anthropic retries on the long-run verbs, a bounded network-retry in the OpenRouter client, and per-item fault tolerance in the calibration proof so one failed call skips-and-logs instead of aborting the whole sweep.

**Architecture:** A `llm_max_retries` config knob + a CLI `_anthropic(config)` helper; a retry-with-backoff loop around the OpenRouter `_post` HTTP call (transient classes only); and try/except at the per-goal-seeding and per-variant-scoring boundaries in `run_calibration_proof`, with a `skipped` count surfaced honestly in `honesty()`.

**Tech Stack:** Python 3.11+, pytest, anthropic SDK, httpx.

## Global Constraints

- Retries are bounded (no unbounded hang). Only transient failures retry: `httpx.TransportError` (covers timeouts) and HTTP `429`/`5xx`. A `4xx` never retries — surfaced immediately.
- Resilience never hides a failure: a skipped calibration item is counted and shown in `honesty()`, never silently dropped. No verdict changes; only whether the run completes and how honestly it reports coverage.
- Broad `except Exception` at the calibrate item boundary must not swallow `KeyboardInterrupt`/`SystemExit` (they are not subclasses of `Exception`, so a bare `except Exception` is already safe).
- Same review-before-push bar as the rest: full-suite gate + adversarial whole-branch review, fix, push only on greenlight.

## File Structure

- `avow/config.py` (modify) — add `llm_max_retries: int = 6`.
- `avow/cli.py` (modify) — add `_anthropic(config)`; use it in `_cmd_survive`, `_cmd_gauntlet`, `_cmd_calibrate_gauntlet`.
- `avow/openrouter.py` (modify) — retry loop + backoff in `_post`.
- `avow/calibration_gauntlet.py` (modify) — `CalibrationProof.skipped`, `honesty()` coverage line, try/except in `run_calibration_proof`.
- Tests: `tests/test_config.py`, `tests/test_cli_*` (a small `_anthropic` test), `tests/test_openrouter.py`, `tests/test_calibration_proof.py`.

---

### Task A: `llm_max_retries` config + `_anthropic(config)` helper on the long-run verbs

**Files:**
- Modify: `avow/config.py`, `avow/cli.py`
- Test: `tests/test_config.py`, `tests/test_cli_calibrate.py` (append)

**Interfaces:**
- Produces: `RunConfig.llm_max_retries: int = 6`; `avow.cli._anthropic(config) -> anthropic.Anthropic` (with `max_retries=config.llm_max_retries`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_config.py`:
```python
def test_llm_max_retries_default():
    assert RunConfig().llm_max_retries == 6
```

Append to `tests/test_cli_calibrate.py`:
```python
def test_anthropic_helper_sets_max_retries():
    from avow.cli import _anthropic
    from avow.config import RunConfig
    c = _anthropic(RunConfig())
    assert c.max_retries == 6
    c2 = _anthropic(RunConfig(llm_max_retries=9))
    assert c2.max_retries == 9
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_config.py::test_llm_max_retries_default tests/test_cli_calibrate.py::test_anthropic_helper_sets_max_retries -q`
Expected: FAIL (`llm_max_retries` missing / `_anthropic` undefined).

- [ ] **Step 3: Add the config knob** in `avow/config.py` (next to `test_timeout_seconds`):
```python
    llm_max_retries: int = 6   # Anthropic SDK default is 2; long multi-call verbs use this
```

- [ ] **Step 4: Add the helper + use it** in `avow/cli.py`. Add at module level (near the other helpers):
```python
def _anthropic(config):
    import anthropic
    return anthropic.Anthropic(max_retries=config.llm_max_retries)
```
Then in `_cmd_survive`, replace `verify_client = anthropic.Anthropic()` with `verify_client = _anthropic(config)`.
In `_cmd_gauntlet`, replace the inline `anthropic.Anthropic()` argument to `run_gauntlet(...)` with `_anthropic(config)`.
In `_cmd_calibrate_gauntlet`, replace `client = anthropic.Anthropic()` with `client = _anthropic(config)`.
(Each of these functions already has `config` in scope.)

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_config.py tests/test_cli_calibrate.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**
```bash
git add avow/config.py avow/cli.py tests/test_config.py tests/test_cli_calibrate.py
git commit -m "feat: llm_max_retries config + _anthropic helper on the long-run verbs (survive/gauntlet/calibrate)"
```

---

### Task B: bounded network retry in the OpenRouter client

**Files:**
- Modify: `avow/openrouter.py`
- Test: `tests/test_openrouter.py` (append)

**Interfaces:**
- Produces: `_post` retries transient failures (`httpx.TransportError`, status `429`/`5xx`) up to `_RETRY_ATTEMPTS` with exponential backoff; `4xx` raises immediately. Module constants `_RETRY_ATTEMPTS = 4`, `_RETRY_BACKOFF = 0.5`.

- [ ] **Step 1: Write the failing tests (append to `tests/test_openrouter.py`)**

```python
import httpx
import avow.openrouter as orm
from avow.openrouter import OpenRouterClient


class _Resp:
    def __init__(self, status_code=200, payload=None, text="ok"):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True}
        self.text = text

    def json(self):
        return self._payload


class _FakeHTTP:
    """Records calls; yields the queued responses/exceptions in order."""
    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script_default
        if isinstance(item, Exception):
            raise item
        return item


def test_post_retries_transient_then_succeeds(monkeypatch):
    monkeypatch.setattr(orm.time, "sleep", lambda *_: None)   # no real backoff sleeps
    http = _FakeHTTP([httpx.ConnectError("boom"), _Resp(200, {"choices": []})])
    c = OpenRouterClient(api_key="k", http_client=http)
    data = c._post({"model": "m"})
    assert data == {"choices": []} and http.calls == 2   # retried once, then succeeded


def test_post_does_not_retry_4xx(monkeypatch):
    monkeypatch.setattr(orm.time, "sleep", lambda *_: None)
    http = _FakeHTTP([_Resp(400, text="bad request")])
    c = OpenRouterClient(api_key="k", http_client=http)
    try:
        c._post({"model": "m"})
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    assert http.calls == 1   # 4xx is permanent -> no retry


def test_post_gives_up_after_budget(monkeypatch):
    monkeypatch.setattr(orm.time, "sleep", lambda *_: None)
    http = _FakeHTTP([httpx.ConnectError("x")] * 10)
    c = OpenRouterClient(api_key="k", http_client=http)
    try:
        c._post({"model": "m"})
        assert False, "expected the transient error to surface"
    except httpx.TransportError:
        pass
    assert http.calls == orm._RETRY_ATTEMPTS   # bounded
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_openrouter.py -q -k "retries or 4xx or budget"`
Expected: FAIL (no retry / no `_RETRY_ATTEMPTS`).

- [ ] **Step 3: Implement the retry loop** in `avow/openrouter.py`. Ensure `import time` and `import httpx` are present at the top, and add near the other module constants:
```python
_RETRY_ATTEMPTS = 4
_RETRY_BACKOFF = 0.5
_RETRYABLE_STATUS = {429}
```
Replace the body of `_post` (after the api_key check + headers/url) with:
```python
        last_exc = None
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                if self._http is not None:
                    resp = self._http.post(url, headers=headers, json=body, timeout=self.timeout)
                else:
                    resp = httpx.post(url, headers=headers, json=body, timeout=self.timeout)
            except httpx.TransportError as exc:   # covers connect errors AND timeouts
                last_exc = exc
                if attempt + 1 < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF * (2 ** attempt))
                    continue
                raise
            if resp.status_code in _RETRYABLE_STATUS or 500 <= resp.status_code < 600:
                last_exc = RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:300]}")
                if attempt + 1 < _RETRY_ATTEMPTS:
                    time.sleep(_RETRY_BACKOFF * (2 ** attempt))
                    continue
                raise last_exc
            if not 200 <= resp.status_code < 300:
                raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text[:300]}")   # 4xx: permanent
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError) as exc:
                raise RuntimeError("OpenRouter returned a non-JSON response") from exc
            if not isinstance(data, dict):
                raise RuntimeError("OpenRouter returned a non-object JSON response")
            return data
        raise last_exc   # unreachable: the loop either returns or raises within
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_openrouter.py -q`
Expected: PASS (existing OpenRouter tests + the 3 new).

- [ ] **Step 5: Commit**
```bash
git add avow/openrouter.py tests/test_openrouter.py
git commit -m "feat: bounded network retry+backoff in OpenRouter _post (transient only; 4xx surfaced immediately)"
```

---

### Task C: per-item fault tolerance in the calibration proof

**Files:**
- Modify: `avow/calibration_gauntlet.py`
- Test: `tests/test_calibration_proof.py` (append)

**Interfaces:**
- Produces: `CalibrationProof.skipped: int = 0`; `honesty()` appends a coverage line when `skipped > 0`; `run_calibration_proof` tolerates a per-goal-seeding or per-variant-scoring failure, counting it in `skipped`.

- [ ] **Step 1: Write the failing test (append to `tests/test_calibration_proof.py`)**

```python
def test_run_proof_tolerates_a_failing_item(monkeypatch):
    import avow.calibration_gauntlet as cg
    from avow.calibration import CalibrationRow
    from avow.calibration_benchmark import FAMILY_GOALS
    from avow.config import RunConfig

    goals = [g for g in FAMILY_GOALS if g.name in ("compare_semver", "max_version")]

    def flaky_eval(goal, src, config, oracle_client):
        if goal.name == "compare_semver":
            raise RuntimeError("transient API error")
        return CalibrationRow(goal=goal.name, variant="", green=True, confidence=1.0,
                              oracle_agreement=None, correct=True)

    monkeypatch.setattr(cg, "_evaluate_variant", flaky_eval)
    monkeypatch.setattr(cg, "score_with_gauntlet", lambda *a, **k: cg.GauntletScore(True, True, 3))
    monkeypatch.setattr(cg, "build_seeded_patterns", lambda *a, **k: [])

    clients = cg.ProofClients(scoring_for=lambda g: object(), mining_for=lambda g: object(),
                              coroner=object(), oracle=None)
    proof = cg.run_calibration_proof(goals, lambda g: "bug_lexical", RunConfig(), clients, with_seed=True)
    assert proof.skipped == 2                      # compare_semver's 2 variants both skipped
    assert proof.plain.trusted == 2                # max_version's 2 variants still scored -> run completed
    assert "skipped due to transient errors" in proof.honesty()


def test_run_proof_no_failures_has_no_coverage_line():
    from avow.calibration_gauntlet import Cohort, CalibrationProof
    out = CalibrationProof(Cohort("plain-green", 0, 2), Cohort("survived (empty graveyard)", 0, 2),
                           Cohort("survived (seeded graveyard)", 0, 2)).honesty()
    assert "skipped" not in out                    # skipped defaults to 0 -> unchanged output
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_calibration_proof.py::test_run_proof_tolerates_a_failing_item -q`
Expected: FAIL (`skipped` attribute missing / the exception propagates and aborts the run).

- [ ] **Step 3: Add `skipped` + the coverage line** in `avow/calibration_gauntlet.py`. Change the dataclass:
```python
@dataclass
class CalibrationProof:
    plain: Cohort
    survived_empty: Cohort
    survived_seeded: Cohort
    seeded_ran: bool = True
    skipped: int = 0   # items dropped due to transient errors (coverage is then undercounted)
```
At the end of `honesty()`, just before `return "\n".join(lines)`:
```python
        if self.skipped:
            lines.append(f"coverage: {self.skipped} item(s) skipped due to transient errors "
                         "-- cohorts are undercounted")
```

- [ ] **Step 4: Wrap the failure-prone units** in `run_calibration_proof`. Replace the loop body with:
```python
    skipped = 0
    for g in goals:
        seed_descriptions = []
        if with_seed:
            try:
                mine_goals = [(og, seed_bug_for(og)) for og in goals if og.name != g.name]
                pats = build_seeded_patterns(mine_goals, g.name, config, clients.mining_for, clients.coroner)
                seed_descriptions = [p.description for p in pats]
            except Exception:
                skipped += 1   # mining failed for this goal; plain/empty cohorts still scored below

        for vname, src in g.variants.items():
            try:
                row = _evaluate_variant(g, src, config, clients.oracle)
                row.variant = vname
                if not is_trusted(row, config.confidence_threshold, use_oracle):
                    continue
                plain.trusted += 1
                plain.wrong += int(not row.correct)

                empty = score_with_gauntlet(g, src, config, clients.scoring_for(g), patterns=[])
                if empty.survived:
                    survived_empty.trusted += 1
                    survived_empty.wrong += int(not row.correct)

                if with_seed:
                    seeded = score_with_gauntlet(g, src, config, clients.scoring_for(g),
                                                 patterns=seed_descriptions)
                    if seeded.survived:
                        survived_seeded.trusted += 1
                        survived_seeded.wrong += int(not row.correct)
            except Exception:
                skipped += 1   # a transient failure on this variant; drop it, keep the sweep alive

    return CalibrationProof(plain, survived_empty, survived_seeded, seeded_ran=with_seed, skipped=skipped)
```

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_calibration_proof.py -q`
Expected: PASS (existing proof tests + the 2 new).

- [ ] **Step 6: Full-suite gate**

Run: `python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 7: Commit**
```bash
git add avow/calibration_gauntlet.py tests/test_calibration_proof.py
git commit -m "feat: calibration proof tolerates transient per-item failures (skip+count) and reports coverage honestly"
```

---

## Manual validation (after Task C, needs ANTHROPIC_API_KEY)

Re-run the scoped real proof (`run_calibration_proof` on the family goals with a live client). With
`llm_max_retries=6` and per-item tolerance, a transient blip now drops one item and annotates
coverage rather than aborting — the sweep completes and emits real (honestly partial if needed)
numbers. This is what both earlier live attempts could not do.

## Out of scope (backlog)

- Retrofitting retries onto the single-call CLI verbs.
- Checkpoint/resume of a partial sweep to disk.
