# Avow — Coroner + Graveyard (sub-project B) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Every gauntlet kill is abstracted into a transferable `AttackPattern` (the Coroner) and persisted in a global Graveyard; future gauntlets seed their reference generation with the graveyard's patterns, so Avow probes the ways it's been fooled before. Empty graveyard → the gauntlet is byte-for-byte sub-project A.

**Architecture:** `avow/graveyard.py` (pure JSONL store), `avow/coroner.py` (LLM abstraction), a one-line seeding hook in `avow/gauntlet.py`, and wiring in `avow/survive.py`. Reuses A's kill machinery and `oracle.generate_oracle`.

**Tech Stack:** Python 3.11+, pydantic, pytest, the `anthropic` SDK (`messages.parse`).

## Global Constraints

- Python **3.11+**. venv at `/Users/qatadaha/Coding/avow/.venv`; activate before every command.
- **Execution still decides every kill.** Seeding only makes references pattern-aware; it never kills on its own.
- **Backward compatible:** `run_gauntlet(patterns=None or [])` is identical to A. Recording happens only when a `coroner_client` is supplied.
- **Tests must be hermetic:** never read/write the real `~/.avow/graveyard.jsonl`; always pass a `graveyard_path` under `tmp_path`.
- **UNTRACKED files stay uncommitted:** `avow/openrouter.py`, `tests/test_openrouter.py`. Specific `git add` per task; never `git add -A`.
- **No `git commit` without go-ahead** — prepared commits run only when greenlit; push only when told.
- Reuse: `gauntlet.Counterexample(input_repr, reference_code, diff_test_code)`, `gauntlet.run_gauntlet`, `oracle.generate_oracle`, `survive.survive` (from A).

## File Structure

- `avow/graveyard.py` (new) — `AttackPattern`, `default_graveyard_path`, `record`, `load`, `recent`.
- `avow/coroner.py` (new) — `abstract_counterexample`.
- `avow/gauntlet.py` (modify) — `run_gauntlet(..., patterns=None)`.
- `avow/survive.py` (modify) — load patterns + record on kill.
- `avow/config.py`, `avow/cli.py` (modify).
- Tests: `tests/test_graveyard.py`, `tests/test_coroner.py`, additions to `tests/test_gauntlet.py`, `tests/test_survive.py`, `tests/test_cli_survive.py`, `tests/test_config.py`.

---

### Task 1: Config knobs

**Files:** Modify `avow/config.py`, `tests/test_config.py`.

**Interfaces:** Produces `RunConfig.coroner_model: str = "claude-opus-4-8"`, `.graveyard_patterns_k: int = 20`, `.graveyard_path: str = ""`.

- [ ] **Step 1: Failing test** — add to `tests/test_config.py::test_defaults_are_sane`:

```python
    assert cfg.coroner_model == "claude-opus-4-8"
    assert cfg.graveyard_patterns_k == 20
    assert cfg.graveyard_path == ""
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_config.py::test_defaults_are_sane -q` → FAIL (`AttributeError`).

- [ ] **Step 3: Add fields** — in `avow/config.py`, next to the `gauntlet_*` fields:

```python
    coroner_model: str = "claude-opus-4-8"
    graveyard_patterns_k: int = 20
    graveyard_path: str = ""
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_config.py -q` → PASS.

- [ ] **Step 5: Prepare commit** (only when greenlit):

```bash
cd /Users/qatadaha/Coding/avow && git add avow/config.py tests/test_config.py && git commit -m "feat: coroner/graveyard config knobs"
```

---

### Task 2: The Graveyard (pure persistent store)

**Files:** Create `avow/graveyard.py`, `tests/test_graveyard.py`.

**Interfaces:** Produces `AttackPattern(category, description, origin_goal="", example_input="")`; `default_graveyard_path() -> Path`; `record(pattern, path) -> bool`; `load(path) -> list[AttackPattern]`; `recent(path, n) -> list[AttackPattern]`.

- [ ] **Step 1: Failing tests** — create `tests/test_graveyard.py`:

```python
from avow.graveyard import AttackPattern, record, load, recent


def _p(cat, desc):
    return AttackPattern(category=cat, description=desc, origin_goal="g", example_input="x")


def test_record_and_load_roundtrip(tmp_path):
    gy = tmp_path / "gy.jsonl"
    assert record(_p("boundary", "probe numeric boundaries"), gy) is True
    loaded = load(gy)
    assert len(loaded) == 1 and loaded[0].category == "boundary"
    assert loaded[0].description == "probe numeric boundaries"


def test_record_dedups_on_category_and_description(tmp_path):
    gy = tmp_path / "gy.jsonl"
    assert record(_p("boundary", "Probe Numeric Boundaries"), gy) is True
    assert record(_p("boundary", "probe numeric boundaries  "), gy) is False   # same key (case/space-insensitive)
    assert len(load(gy)) == 1


def test_recent_returns_last_n_in_order(tmp_path):
    gy = tmp_path / "gy.jsonl"
    for i in range(5):
        record(_p("c", f"pattern {i}"), gy)
    r = recent(gy, 2)
    assert [p.description for p in r] == ["pattern 3", "pattern 4"]


def test_load_missing_file_is_empty(tmp_path):
    assert load(tmp_path / "nope.jsonl") == []


def test_load_skips_corrupt_lines(tmp_path):
    gy = tmp_path / "gy.jsonl"
    record(_p("c", "good"), gy)
    with gy.open("a") as f:
        f.write("not json\n{}\n")
    assert [p.description for p in load(gy)] == ["good"]   # corrupt/incomplete lines skipped
```

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_graveyard.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `avow/graveyard.py`**:

```python
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel


class AttackPattern(BaseModel):
    category: str          # short slug, e.g. "numeric-boundary" | "empty-input" | "unicode-edge"
    description: str        # transferable attack strategy (NOT the literal input)
    origin_goal: str = ""   # one-line summary of the goal it arose from (provenance)
    example_input: str = ""  # the concrete falsifying example that spawned it


def default_graveyard_path() -> Path:
    return Path.home() / ".avow" / "graveyard.jsonl"


def _key(p: AttackPattern) -> tuple:
    return (p.category.strip().lower(), p.description.strip().lower())


def load(path) -> list:
    p = Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(AttackPattern(**json.loads(line)))
        except (json.JSONDecodeError, TypeError, ValueError):
            continue   # skip corrupt / incomplete lines — the store is best-effort
    return out


def record(pattern: AttackPattern, path) -> bool:
    """Append the pattern iff its (category, description) key is new. Returns whether it was recorded."""
    p = Path(path)
    if _key(pattern) in {_key(x) for x in load(p)}:
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(pattern.model_dump_json() + "\n")
    return True


def recent(path, n: int) -> list:
    return load(path)[-n:] if n > 0 else []
```

- [ ] **Step 4: Run to verify they pass** — `python -m pytest tests/test_graveyard.py -q` → PASS (5 passed).

- [ ] **Step 5: Prepare commit** (only when greenlit):

```bash
cd /Users/qatadaha/Coding/avow && git add avow/graveyard.py tests/test_graveyard.py && git commit -m "feat: the Graveyard — global attack-pattern store (record/load/recent, deduped)"
```

---

### Task 3: The Coroner (LLM abstraction)

**Files:** Create `avow/coroner.py`, `tests/test_coroner.py`.

**Interfaces:** Consumes `graveyard.AttackPattern`, `gauntlet.Counterexample`. Produces `abstract_counterexample(counterexample, goal, client, model) -> tuple[AttackPattern | None, int, int]`.

- [ ] **Step 1: Failing tests** — create `tests/test_coroner.py`:

```python
from types import SimpleNamespace
from avow.coroner import abstract_counterexample
from avow.graveyard import AttackPattern
from avow.gauntlet import Counterexample


class _FakeCoroner:
    def __init__(self):
        self.last_content = None

    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        assert output_format is AttackPattern
        self.last_content = kwargs["messages"][0]["content"]
        po = AttackPattern(category="numeric-boundary",
                           description="probe where a numeric field meets a longer numeric field",
                           origin_goal="semver compare", example_input="test_diff(a='2', b='11')")
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=3, output_tokens=4))


def _cx():
    return Counterexample(input_repr="test_diff(a='2', b='11')",
                          reference_code="def cmp(a, b): ...", diff_test_code="...")


def test_abstract_produces_pattern_and_tokens():
    client = _FakeCoroner()
    pattern, i, o = abstract_counterexample(_cx(), "compare semver strings", client, "m")
    assert isinstance(pattern, AttackPattern)
    assert pattern.category == "numeric-boundary" and pattern.description
    assert i == 3 and o == 4
    # the prompt carried the goal and the concrete counterexample
    assert "compare semver strings" in client.last_content and "test_diff(a='2', b='11')" in client.last_content


def test_abstract_no_client_is_noop():
    assert abstract_counterexample(_cx(), "goal", None, "m") == (None, 0, 0)
```

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_coroner.py -q` → FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Write `avow/coroner.py`**:

```python
from __future__ import annotations

from avow.graveyard import AttackPattern

_CORONER_PROMPT = """\
You are a CORONER for a code verifier. A solution was just KILLED: on a specific input it diverged \
from an independently written, correct reference implementation. Perform an autopsy and abstract the \
death into a TRANSFERABLE attack pattern — a CLASS of inputs likely to break OTHER programs too, not \
the one literal input.

Return:
- category: a short kebab-case slug for the failure class (e.g. "numeric-boundary", "empty-input", \
"unicode-edge", "off-by-one", "ordering-tie").
- description: one or two sentences describing the reusable attack STRATEGY (what class of inputs to \
probe and why), phrased so it applies beyond this specific goal.
- origin_goal: a one-line summary of the goal this arose from.
- example_input: the literal falsifying input, verbatim.

GOAL:
{goal}

THE KILLING INPUT (Hypothesis falsifying example):
{example}

THE CORRECT REFERENCE IT DIVERGED FROM:
{reference}
"""


def abstract_counterexample(counterexample, goal, client, model) -> tuple:
    if client is None:
        return None, 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=1000,
        messages=[{"role": "user", "content": _CORONER_PROMPT.format(
            goal=goal, example=counterexample.input_repr, reference=counterexample.reference_code)}],
        output_format=AttackPattern,
    )
    usage = response.usage
    return (response.parsed_output,
            getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0))
```

- [ ] **Step 4: Run to verify they pass** — `python -m pytest tests/test_coroner.py -q` → PASS (2 passed).

- [ ] **Step 5: Prepare commit** (only when greenlit):

```bash
cd /Users/qatadaha/Coding/avow && git add avow/coroner.py tests/test_coroner.py && git commit -m "feat: the Coroner — abstract a counterexample into a transferable AttackPattern"
```

---

### Task 4: Gauntlet seeding

**Files:** Modify `avow/gauntlet.py`, `tests/test_gauntlet.py`.

**Interfaces:** `run_gauntlet(solution_dir, goal, client, model, test_command, *, k=4, examples=200, timeout=120, patterns=None)`. When `patterns` is non-empty, reference generation uses a goal augmented with the pattern descriptions.

- [ ] **Step 1: Failing tests** — append to `tests/test_gauntlet.py`:

```python
class _CapturingClient:
    def __init__(self):
        self.last_content = None

    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        self.last_content = kwargs["messages"][0]["content"]
        po = _OraclePair(reference_code="def f(x):\n    return x + 1\n", diff_test_code=_DIFF)
        return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_run_gauntlet_seeds_references_with_patterns(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    c = _CapturingClient()
    run_gauntlet(tmp_path, "f(x) returns x+1", c, "m", TEST_CMD, k=1, examples=20, timeout=60,
                 patterns=["probe empty and boundary inputs"])
    assert "probe empty and boundary inputs" in c.last_content


def test_run_gauntlet_no_patterns_is_unchanged(tmp_path):
    (tmp_path / "lib.py").write_text("def f(x):\n    return x + 1\n")
    c = _CapturingClient()
    run_gauntlet(tmp_path, "GOALTEXT_MARKER", c, "m", TEST_CMD, k=1, examples=20, timeout=60)
    assert "GOALTEXT_MARKER" in c.last_content and "known-tricky" not in c.last_content
```

- [ ] **Step 2: Run to verify they fail** — `python -m pytest tests/test_gauntlet.py -q -k patterns` → FAIL (`patterns` not accepted / assertion).

- [ ] **Step 3: Edit `run_gauntlet`** in `avow/gauntlet.py` — change the signature and augment the goal for reference generation:

```python
def run_gauntlet(solution_dir, goal, client, model, test_command, *,
                 k: int = 4, examples: int = 200, timeout: int = 120, patterns=None) -> GauntletResult:
```

and, right after the `if client is None:` guard, before the loop:

```python
    goal_for_refs = goal
    if patterns:
        goal_for_refs = goal + (
            "\n\nA rigorous differential test MUST cover these known-tricky input classes "
            "(ways past solutions have been fooled):\n" + "\n".join(f"- {p}" for p in patterns))
```

and inside the loop change `generate_oracle(goal, client, model)` to `generate_oracle(goal_for_refs, client, model)`.

- [ ] **Step 4: Run to verify they pass** — `python -m pytest tests/test_gauntlet.py -q` → PASS (all, incl. the existing A tests unchanged since `patterns` defaults `None`).

- [ ] **Step 5: Prepare commit** (only when greenlit):

```bash
cd /Users/qatadaha/Coding/avow && git add avow/gauntlet.py tests/test_gauntlet.py && git commit -m "feat: gauntlet seeding — pattern-aware reference generation (empty patterns == unchanged)"
```

---

### Task 5: Wire the Coroner + Graveyard into `survive`

**Files:** Modify `avow/survive.py`, `tests/test_survive.py`.

**Interfaces:** `survive(..., coroner_client=None, ...)`. Loads recent patterns, passes them to `run_gauntlet`, records each kill's pattern.

- [ ] **Step 1: Failing test** — first make the existing survive tests hermetic (pass `graveyard_path` to a temp so none touch `~/.avow`). Add `graveyard_path=str(tmp_path / "gy.jsonl")` to the `RunConfig(...)` in every existing test in `tests/test_survive.py`. Then append:

```python
class _FakeCoroner:
    @property
    def messages(self):
        return self

    def parse(self, *, output_format, **kwargs):
        from avow.graveyard import AttackPattern
        return SimpleNamespace(
            parsed_output=AttackPattern(category="c", description="d", origin_goal="g", example_input="x"),
            usage=SimpleNamespace(input_tokens=1, output_tokens=1))


def test_survive_records_pattern_on_kill(tmp_path, monkeypatch):
    import avow.survive as s
    from avow.graveyard import load
    gy = tmp_path / "gy.jsonl"
    calls = {"n": 0}

    def fake_g(*a, **k):
        calls["n"] += 1
        return GauntletResult(False, _CX, 4, 4, 0, 0) if calls["n"] == 1 else GauntletResult(True, None, 4, 4, 0, 0)

    monkeypatch.setattr(s, "run_gauntlet", fake_g)
    r = survive(_goal(tmp_path),
                RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=3, graveyard_path=str(gy)),
                StubExaminer(), GoodBuilder(), gauntlet_client=object(), coroner_client=_FakeCoroner(), now=lambda: 0.0)
    assert r.status == "verified_survivor"
    assert len(load(gy)) == 1   # the one kill was abstracted + recorded


def test_survive_no_coroner_records_nothing(tmp_path, monkeypatch):
    import avow.survive as s
    from avow.graveyard import load
    gy = tmp_path / "gy.jsonl"
    monkeypatch.setattr(s, "run_gauntlet", lambda *a, **k: GauntletResult(False, _CX, 4, 4, 0, 0))
    survive(_goal(tmp_path),
            RunConfig(max_iterations=5, holdout_fraction=0.0, gauntlet_max_rounds=1, graveyard_path=str(gy)),
            StubExaminer(), GoodBuilder(), gauntlet_client=object(), coroner_client=None, now=lambda: 0.0)
    assert load(gy) == []   # no coroner -> nothing recorded
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_survive.py::test_survive_records_pattern_on_kill -q` → FAIL (`coroner_client` unexpected / nothing recorded).

- [ ] **Step 3: Edit `avow/survive.py`** — add imports, the `coroner_client` param, load patterns, and record on kill:

Add imports:

```python
from avow.graveyard import recent, record, default_graveyard_path
from avow.coroner import abstract_counterexample
```

Change the signature to include `coroner_client=None` (keyword-only, alongside `gauntlet_client`):

```python
def survive(goal_dir, config, examiner, builder, *, gauntlet_client, coroner_client=None,
            mutation_client=None, intent_client=None, property_client=None, oracle_client=None,
            now=time.monotonic) -> SurviveResult:
```

After the `if gauntlet_client is None:` guard, before the loop:

```python
    graveyard_path = config.graveyard_path or str(default_graveyard_path())
    patterns = [p.description for p in recent(graveyard_path, config.graveyard_patterns_k)]
```

Pass `patterns=patterns` to the `run_gauntlet(...)` call. And immediately after `last_cx = g.counterexample`, record the death:

```python
        if coroner_client is not None:
            pat, _i, _o = abstract_counterexample(g.counterexample, goal, coroner_client, config.coroner_model)
            if pat is not None:
                record(pat, graveyard_path)   # best-effort; never changes the verdict
```

- [ ] **Step 4: Run to verify it passes** — `python -m pytest tests/test_survive.py -q` → PASS (existing + 2 new; all hermetic).

- [ ] **Step 5: Prepare commit** (only when greenlit):

```bash
cd /Users/qatadaha/Coding/avow && git add avow/survive.py tests/test_survive.py && git commit -m "feat: survive records each kill (Coroner->Graveyard) and seeds gauntlets with recent patterns"
```

---

### Task 6: CLI — pass the coroner, add `avow graveyard`

**Files:** Modify `avow/cli.py`, `tests/test_cli_survive.py`.

**Interfaces:** `avow survive` passes `coroner_client`; `--graveyard <path>` on `survive`/`graveyard`; new `avow graveyard [--graveyard <path>]` lists the store.

- [ ] **Step 1: Failing test** — append to `tests/test_cli_survive.py`:

```python
def test_graveyard_cli_lists_patterns(tmp_path, capsys):
    from avow.graveyard import record, AttackPattern
    gy = tmp_path / "gy.jsonl"
    record(AttackPattern(category="numeric-boundary", description="probe range boundaries"), gy)
    record(AttackPattern(category="empty-input", description="probe empty and null inputs"), gy)
    rc = cli.main(["graveyard", "--graveyard", str(gy)])
    out = capsys.readouterr().out
    assert rc == 0
    assert "2 patterns" in out
    assert "numeric-boundary" in out and "probe empty and null inputs" in out
```

- [ ] **Step 2: Run to verify it fails** — `python -m pytest tests/test_cli_survive.py::test_graveyard_cli_lists_patterns -q` → FAIL (`invalid choice: 'graveyard'`).

- [ ] **Step 3: Add the handler** to `avow/cli.py` (next to `_cmd_survive`):

```python
def _cmd_graveyard(args) -> int:
    from avow.graveyard import load, default_graveyard_path

    path = args.graveyard or str(default_graveyard_path())
    patterns = load(path)
    print(f"graveyard: {path}  ({len(patterns)} patterns)")
    for p in patterns:
        print(f"  [{p.category}] {p.description}")
    return 0
```

- [ ] **Step 4: Wire the coroner into `_cmd_survive`** — in `_cmd_survive`, add the `--graveyard` override and pass `coroner_client`:

```python
    if args.graveyard:
        config.graveyard_path = args.graveyard
    result = survive(Path(args.goal_dir), config, examiner, builder,
                     gauntlet_client=verify_client, coroner_client=verify_client,
                     intent_client=verify_client, property_client=verify_client, oracle_client=verify_client)
```

- [ ] **Step 5: Add subparsers + dispatch** in `main()`:

Next to the `survive_p` subparser, add `--graveyard` to `survive_p` and a new `graveyard_p`:

```python
    survive_p.add_argument("--graveyard", default=None)
    graveyard_p = sub.add_parser("graveyard", help="list the global attack-pattern memory (what Avow has learned)")
    graveyard_p.add_argument("--graveyard", default=None)
```

Next to the `survive`/`gauntlet` dispatch:

```python
    if args.command == "graveyard":
        return _cmd_graveyard(args)
```

- [ ] **Step 6: Run to verify it passes + smoke** — `python -m pytest tests/test_cli_survive.py -q && avow --help | grep graveyard` → PASS; `--help` lists `graveyard`.

- [ ] **Step 7: Run the whole suite** — `python -m pytest -q` → PASS, 0 warnings.

- [ ] **Step 8: Prepare commit** (only when greenlit):

```bash
cd /Users/qatadaha/Coding/avow && git add avow/cli.py tests/test_cli_survive.py && git commit -m "feat: avow survive records deaths + avow graveyard lists the learned patterns"
```

---

## Manual validation (after Task 6, needs ANTHROPIC_API_KEY)

Run `avow survive` on a goal whose first green hides a bug → confirm it kills, and `avow graveyard` then lists a new pattern. Run `avow survive` on a *second, different* goal → confirm its gauntlet references were seeded (the death of the first informs the second). This is anecdotal; sub-project C provides the measured proof.

## Out of scope (backlog)

- **C — Calibration proof:** `avow calibrate` measuring survivors' false-high-confidence with an empty vs seeded graveyard.
- LLM/embedding relevance retrieval; cross-provider seeded references (OpenRouter).
