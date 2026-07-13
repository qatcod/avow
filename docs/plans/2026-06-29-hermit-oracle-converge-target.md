# Avow — Reference-Oracle as a Converge Target — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Opt-in `oracle_converge_target`: fold the reference's Hypothesis differential test into the frozen suite up front, so the Builder must agree with an independent reference *during* convergence.

**Architecture:** A loop hook in `solve()`'s `write_tests` block reuses the existing `generate_oracle` to write `ref.py` + a diff test into `tests_frozen/` (the un-gameable suite). Off by default; `solve()`'s signature is unchanged (it already takes `oracle_client`).

**Tech Stack:** Python 3.12 · reuses `avow.oracle.generate_oracle` · `avow.examiner.TestFile` · `hypothesis` · `avow.loop`/`avow.config`.

## Global Constraints

- Python **3.11+** (Avow-local venv at `/Users/qatadaha/Coding/avow/.venv`, 3.12). Activate it for every command: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && <cmd>`.
- **Anti-cheat preserved:** `ref.py` + the diff test go into `tests_frozen/` (the Builder never sees it); the diff test is a VISIBLE converge target (never held out).
- **Off by default** (`oracle_converge_target = False`) — existing behavior unchanged when off or no `oracle_client`.
- Reuses verified interfaces (do NOT modify): `generate_oracle(goal, client, model) -> tuple[_OraclePair | None, int, int]` from `avow.oracle`; `TestFile(path, content)` from `avow.examiner`; `_write_tests`/`split_suite`; `solve(...)` already has `oracle_client`.
- **No `git commit` without the user's explicit go-ahead** — each task ends with a prepared commit run when greenlit.

---

### Task 1: `RunConfig.oracle_converge_target`

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/config.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_config.py`

**Interfaces:**
- `RunConfig` gains `oracle_converge_target: bool = False`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.oracle_converge_target is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py::test_defaults_are_sane -q`
Expected: FAIL — `AttributeError: ... 'oracle_converge_target'`.

- [ ] **Step 3: Edit `avow/config.py`**

Add after `oracle_floor`:

```python
    oracle_converge_target: bool = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_config.py -q`
Expected: PASS.

- [ ] **Step 5: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/config.py tests/test_config.py && git commit -m "feat: oracle_converge_target setting on RunConfig (off by default)"
```

---

### Task 2: Loop hook — fold the reference diff test into the frozen suite

**Files:**
- Modify: `/Users/qatadaha/Coding/avow/avow/loop.py`
- Modify: `/Users/qatadaha/Coding/avow/tests/test_loop.py`

**Interfaces:**
- No signature change (`solve` already takes `oracle_client`). Imports `generate_oracle` from `avow.oracle` and `TestFile` from `avow.examiner`.

**Edits (read `avow/loop.py`'s `write_tests` block first):**
- The `write_tests` block currently: writes the Examiner suite, `split_suite` → `visible, held`, the property hook (`visible = visible + props`), then `_write_tests(frozen, visible)` / `_write_tests(holdout, held)`.
- Insert the oracle-converge hook AFTER the property hook and BEFORE `_write_tests(frozen, visible)`:
  ```python
  oracle_ref_code = None
  if config.oracle_converge_target and oracle_client is not None:
      pair, o_in, o_out = generate_oracle(goal, oracle_client, config.oracle_model)
      budget.charge_tokens(config.oracle_model, o_in, o_out)
      if pair is not None:
          visible = visible + [TestFile(path="test_oracle_converge.py", content=pair.diff_test_code)]
          oracle_ref_code = pair.reference_code
  ```
- AFTER `_write_tests(frozen, visible)` (and `_write_tests(holdout, held)`), write the reference module into the frozen dir so the diff test can import it:
  ```python
  if oracle_ref_code is not None:
      (frozen / "ref.py").write_text(oracle_ref_code, encoding="utf-8")
  ```
- Add the imports near the top of `loop.py`: `from avow.oracle import generate_oracle` (loop.py already imports `run_oracle_check` from `avow.oracle` — add `generate_oracle` to that import or a new line) and `from avow.examiner import TestFile` (confirm whether `TestFile` is already imported; add if not).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_loop.py`:

```python
def test_loop_oracle_converge_target(tmp_path):
    from types import SimpleNamespace
    from avow.oracle import _OraclePair

    class FakeOracle:
        @property
        def messages(self):
            return self

        def parse(self, **kwargs):
            pair = _OraclePair(
                reference_code="def add(a, b):\n    return a + b\n",
                diff_test_code=("from lib import add as _sol\nfrom ref import add as _ref\n"
                                "from hypothesis import given, strategies as st\n"
                                "@given(st.integers(), st.integers())\n"
                                "def test_conv(a, b):\n    assert _sol(a, b) == _ref(a, b)\n"))
            return SimpleNamespace(parsed_output=pair, usage=SimpleNamespace(input_tokens=1, output_tokens=1))

    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0, oracle_converge_target=True)
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0,
              oracle_client=FakeOracle())
    # the converged solution (a + b) passes the Examiner test AND agrees with the reference (a + b)
    assert r.success is True and r.reason == "green"
    assert (tmp_path / "tests_frozen" / "test_oracle_converge.py").exists()
    assert (tmp_path / "tests_frozen" / "ref.py").exists()


def test_loop_oracle_converge_target_off_by_default(tmp_path):
    cfg = RunConfig(max_iterations=5, holdout_fraction=0.0)  # oracle_converge_target defaults False
    r = solve(_goal(tmp_path), cfg, StubExaminer(), FlakyBuilder(), now=lambda: 0.0)
    assert r.success is True
    assert not (tmp_path / "tests_frozen" / "ref.py").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_loop.py::test_loop_oracle_converge_target -q`
Expected: FAIL — `tests_frozen/ref.py` does not exist (hook not wired yet).

- [ ] **Step 3: Apply the edits above to `avow/loop.py`**

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest tests/test_loop.py -q`
Expected: PASS — the two new tests (the diff test imports `from ref import add` and fuzzes `a+b == a+b` → passes; the Builder converges) + all existing loop tests (which pass no `oracle_client` and leave `oracle_converge_target` False → the hook never fires → identical behavior).

- [ ] **Step 5: Run the whole suite**

Run: `cd /Users/qatadaha/Coding/avow && source .venv/bin/activate && python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 6: Prepare commit** (run only when greenlit)

```bash
cd /Users/qatadaha/Coding/avow && git add avow/loop.py tests/test_loop.py && git commit -m "feat: oracle converge target — fold the reference diff test into the frozen suite"
```

---

## Manual validation (after Task 2, with credentials)

`avow solve <goal-dir>` with `avow.yaml` setting `oracle_converge_target: true` → the Builder must agree with an independent reference (fuzzed during the build), not just pass the Examiner's tests. A reference that contradicts the Examiner's suite makes the build fail (surfacing the conflict) rather than silently corrupting the solution.

## What this deliberately does NOT do (later)

- Multiple references / cross-reference agreement.
- A cross-provider reference (needs non-Anthropic clients).
- Auto-dropping a contradictory reference (it currently fails the build, which surfaces the conflict).
