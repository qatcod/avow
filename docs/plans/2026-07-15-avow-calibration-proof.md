# Calibration Proof (sub-project C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, on a labeled benchmark, whether gauntlet-survived greens are less often wrong-when-trusted than plain greens, and whether a graveyard seeded (leave-one-out) from other goals' deaths catches more false-greens than an empty one — reporting honest counts with an n-gated multiplier.

**Architecture:** Extend the existing calibration engine, don't fork it. `avow/calibration.py` stays as-is; a new focused `avow/calibration_gauntlet.py` adds the gauntlet stage, the leave-one-out seeding, and the three-cohort proof report. A related goal family (shared numeric-vs-lexical failure class) is added to `avow/calibration_benchmark.py` so transfer can actually be observed. A deterministic seeding-aware stub reference client makes the whole thing CI-green without an API key; real Anthropic clients run only under `--llm`.

**Tech Stack:** Python 3.11+, pytest + pytest-json-report, Hypothesis, pydantic, anthropic SDK.

## Global Constraints

- Python 3.11+. Reuse existing modules; do not fork `calibration.py`.
- The engine module `avow/calibration_gauntlet.py` MUST NOT import `avow/calibration_benchmark.py` (data depends on engine, never the reverse). The CLI wires benchmark data into the engine.
- "survived K references" is NEVER printed or named as "correct". Retain the existing `calibrate` disclaimer.
- No "N× less likely" multiplier is printed unless BOTH compared cohorts have `trusted >= MIN_N`. `MIN_N` default 8. Always print raw `wrong/trusted (n=…)`.
- Leakage guard is **provenance-based**: a seed pattern is leakage iff it was mined FROM the held-out goal (`AttackPattern.origin_goal == held_out_name`). Token overlap is NOT leakage — the family deliberately shares boundary tokens (that is the transfer being measured). `mine_pattern` stamps `origin_goal` authoritatively.
- Deterministic in CI: stub clients only; real numbers only under `--llm`, labeled `n=…, LLM references, single run`.
- All store writes / temp dirs are hermetic (temp paths, never `~/.avow`).
- Same review-before-push bar as A and B: full-suite gate + adversarial whole-branch review + fix, then push only on greenlight.

## File Structure

- `avow/calibration_benchmark.py` (modify) — add `FAMILY_GOALS` (4 `CalibrationGoal`s), `FAMILY_FIXTURES` (per-goal gauntlet fixtures: reference source, strong/weak diff tests, seed-bug variant name), and stub client builders `make_scoring_stub` / `make_mining_stub`.
- `avow/calibration_gauntlet.py` (create) — `GauntletScore`, `score_with_gauntlet`; `LeakageError`, `assert_no_leakage`, `mine_pattern`, `build_seeded_patterns`; `Cohort`, `CalibrationProof` (+ `honesty`); `ProofClients`, `run_calibration_proof`.
- `avow/cli.py` (modify) — extend `_cmd_calibrate` and its subparser with `--gauntlet` / `--llm` / `--seed`.
- Tests: `tests/test_calibration_family.py`, `tests/test_calibration_gauntlet.py`, `tests/test_calibration_proof.py`, and additions to `tests/test_cli_calibrate.py` (create if absent).

---

### Task 1: The related goal family (data + oracles + fixtures)

**Files:**
- Modify: `avow/calibration_benchmark.py`
- Test: `tests/test_calibration_family.py`

**Interfaces:**
- Consumes: `CalibrationGoal(name, goal_text, tests, variants, oracle)` from `avow/calibration.py`; `_load_module(src)` from `avow/calibration.py`.
- Produces: `FAMILY_GOALS: list[CalibrationGoal]`; `FAMILY_FIXTURES: dict[str, Fixture]` where `Fixture` has `.reference_src: str`, `.diff_strong: str`, `.diff_weak: str`, `.seed_bug: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calibration_family.py
from avow.calibration import _load_module
from avow.calibration_benchmark import FAMILY_GOALS, FAMILY_FIXTURES
from avow.runner import Runner
from avow.config import RunConfig
from pathlib import Path
import tempfile


def _green_under_suite(goal, src):
    cfg = RunConfig()
    with tempfile.TemporaryDirectory() as sol, tempfile.TemporaryDirectory() as tst:
        (Path(sol) / "lib.py").write_text(src)
        for fn, content in goal.tests.items():
            (Path(tst) / fn).write_text(content)
        return Runner(Path(sol), Path(tst), cfg.test_command, timeout=cfg.test_timeout_seconds).run().is_green


def test_family_goals_are_well_formed_false_greens():
    assert {g.name for g in FAMILY_GOALS} == {"compare_semver", "max_version", "sort_versions", "is_newer"}
    for g in FAMILY_GOALS:
        ref = g.variants["reference"]
        # reference: green under the (imperfect) suite AND oracle-correct
        assert _green_under_suite(g, ref) is True
        assert g.oracle(_load_module(ref)) is True
        # the injected bug: green under the suite (survives it) BUT oracle-wrong -> a real false-green
        bug = g.variants["bug_lexical"]
        assert _green_under_suite(g, bug) is True
        assert g.oracle(_load_module(bug)) is False


def test_family_fixtures_cover_every_goal():
    for g in FAMILY_GOALS:
        f = FAMILY_FIXTURES[g.name]
        assert f.seed_bug in g.variants
        assert "known-tricky" not in f.diff_weak    # weak diff must not itself be a seeded/strong test
        assert f.reference_src.strip()
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_calibration_family.py -q`
Expected: FAIL with `ImportError: cannot import name 'FAMILY_GOALS'`.

- [ ] **Step 3: Add the family goals + fixtures**

Append to `avow/calibration_benchmark.py`:

```python
from dataclasses import dataclass


@dataclass
class Fixture:
    reference_src: str
    diff_strong: str    # Hypothesis diff test that samples the multi-digit boundary (catches the lexical bug)
    diff_weak: str      # single-digit-only diff test (lexical bug slips through)
    seed_bug: str       # the variant name of the false-green bug to mine a pattern from


# ---- compare_semver(a, b) -> -1/0/1 --------------------------------------------------------------
_CS_REF = ("def compare_semver(a, b):\n"
           "    ta = [int(x) for x in a.split('.')]\n"
           "    tb = [int(x) for x in b.split('.')]\n"
           "    return (ta > tb) - (ta < tb)\n")
_CS_BUG = "def compare_semver(a, b):\n    return (a > b) - (a < b)\n"   # lexical: '2.11' < '2.2'


def _oracle_compare_semver(m):
    return (m.compare_semver("2.11", "2.2") == 1 and m.compare_semver("2.2", "2.11") == -1
            and m.compare_semver("1.0", "1.0") == 0 and m.compare_semver("9.0", "10.0") == -1)


_CS_DIFF_STRONG = (
    "from lib import compare_semver as _sol\nfrom ref import compare_semver as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")
_CS_DIFF_WEAK = (
    "from lib import compare_semver as _sol\nfrom ref import compare_semver as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '3.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")


# ---- max_version(versions) -> str ----------------------------------------------------------------
_MV_REF = ("def max_version(versions):\n"
           "    return max(versions, key=lambda v: [int(x) for x in v.split('.')])\n")
_MV_BUG = "def max_version(versions):\n    return max(versions)\n"   # lexical: '9.0' > '10.0'


def _oracle_max_version(m):
    return m.max_version(["9.0", "10.0"]) == "10.0" and m.max_version(["2.2", "2.11"]) == "2.11"


_MV_DIFF_STRONG = (
    "from lib import max_version as _sol\nfrom ref import max_version as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")
_MV_DIFF_WEAK = (
    "from lib import max_version as _sol\nfrom ref import max_version as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '3.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")


# ---- sort_versions(versions) -> list -------------------------------------------------------------
_SV_REF = ("def sort_versions(versions):\n"
           "    return sorted(versions, key=lambda v: [int(x) for x in v.split('.')])\n")
_SV_BUG = "def sort_versions(versions):\n    return sorted(versions)\n"   # lexical: '10.0' before '2.0'


def _oracle_sort_versions(m):
    return (m.sort_versions(["10.0", "2.0"]) == ["2.0", "10.0"]
            and m.sort_versions(["2.11", "2.2"]) == ["2.2", "2.11"])


_SV_DIFF_STRONG = (
    "from lib import sort_versions as _sol\nfrom ref import sort_versions as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")
_SV_DIFF_WEAK = (
    "from lib import sort_versions as _sol\nfrom ref import sort_versions as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_L = st.lists(st.sampled_from(['1.0', '2.0', '3.0']), min_size=1, max_size=4)\n"
    "@given(_L)\ndef test_diff(vs):\n    assert _sol(vs) == _ref(vs)\n")


# ---- is_newer(a, b) -> bool ----------------------------------------------------------------------
_IN_REF = ("def is_newer(a, b):\n"
           "    return [int(x) for x in a.split('.')] > [int(x) for x in b.split('.')]\n")
_IN_BUG = "def is_newer(a, b):\n    return a > b\n"   # lexical: '2.11' <= '2.2'


def _oracle_is_newer(m):
    return (m.is_newer("2.11", "2.2") is True and m.is_newer("2.2", "2.11") is False
            and m.is_newer("10.0", "9.0") is True)


_IN_DIFF_STRONG = (
    "from lib import is_newer as _sol\nfrom ref import is_newer as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '2.2', '2.11', '9.0', '10.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")
_IN_DIFF_WEAK = (
    "from lib import is_newer as _sol\nfrom ref import is_newer as _ref\n"
    "from hypothesis import given, strategies as st\n"
    "_V = st.sampled_from(['1.0', '2.0', '3.0'])\n"
    "@given(_V, _V)\ndef test_diff(a, b):\n    assert _sol(a, b) == _ref(a, b)\n")


def _suite(fn_import, *cases):
    body = "".join(f"    assert {c}\n" for c in cases)
    return {"test_basic.py": f"from lib import {fn_import}\ndef test_basic():\n{body}"}


FAMILY_GOALS = [
    CalibrationGoal(
        name="compare_semver",
        goal_text="compare_semver(a, b): return -1/0/1 comparing two dotted numeric version strings numerically.",
        tests=_suite("compare_semver as C",
                     "C('1.0', '2.0') == -1", "C('2.0', '2.0') == 0", "C('3.0', '1.0') == 1"),
        variants={"reference": _CS_REF, "bug_lexical": _CS_BUG},
        oracle=_oracle_compare_semver),
    CalibrationGoal(
        name="max_version",
        goal_text="max_version(versions): return the largest dotted numeric version string.",
        tests=_suite("max_version as M", "M(['1.0', '2.0']) == '2.0'", "M(['3.0', '1.0', '2.0']) == '3.0'"),
        variants={"reference": _MV_REF, "bug_lexical": _MV_BUG},
        oracle=_oracle_max_version),
    CalibrationGoal(
        name="sort_versions",
        goal_text="sort_versions(versions): return the versions sorted ascending by numeric order.",
        tests=_suite("sort_versions as S",
                     "S(['2.0', '1.0']) == ['1.0', '2.0']", "S(['3.0', '1.0', '2.0']) == ['1.0', '2.0', '3.0']"),
        variants={"reference": _SV_REF, "bug_lexical": _SV_BUG},
        oracle=_oracle_sort_versions),
    CalibrationGoal(
        name="is_newer",
        goal_text="is_newer(a, b): return True iff dotted numeric version a is strictly newer than b.",
        tests=_suite("is_newer as N",
                     "N('2.0', '1.0') is True", "N('1.0', '2.0') is False", "N('1.0', '1.0') is False"),
        variants={"reference": _IN_REF, "bug_lexical": _IN_BUG},
        oracle=_oracle_is_newer),
]

FAMILY_FIXTURES = {
    "compare_semver": Fixture(_CS_REF, _CS_DIFF_STRONG, _CS_DIFF_WEAK, "bug_lexical"),
    "max_version": Fixture(_MV_REF, _MV_DIFF_STRONG, _MV_DIFF_WEAK, "bug_lexical"),
    "sort_versions": Fixture(_SV_REF, _SV_DIFF_STRONG, _SV_DIFF_WEAK, "bug_lexical"),
    "is_newer": Fixture(_IN_REF, _IN_DIFF_STRONG, _IN_DIFF_WEAK, "bug_lexical"),
}
```

Note: `CalibrationGoal` and `_load_module` are already imported/defined in the module's existing top section (`from avow.calibration import CalibrationGoal`); reuse them.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_calibration_family.py -q`
Expected: PASS (2 tests). The reference is green+correct; each bug is green-under-suite but oracle-wrong.

- [ ] **Step 5: Commit**

```bash
git add avow/calibration_benchmark.py tests/test_calibration_family.py
git commit -m "feat: calibration family goals (numeric-vs-lexical boundary) + gauntlet fixtures"
```

---

### Task 2: `score_with_gauntlet` + seeding-aware stub reference clients

**Files:**
- Create: `avow/calibration_gauntlet.py`
- Modify: `avow/calibration_benchmark.py` (add `make_scoring_stub`, `make_mining_stub`)
- Test: `tests/test_calibration_gauntlet.py`

**Interfaces:**
- Consumes: `run_gauntlet(...)` and `GauntletResult` from `avow/gauntlet.py`; `Runner` from `avow/runner.py`; `_OraclePair` from `avow/oracle.py`; `FAMILY_GOALS`, `FAMILY_FIXTURES` from Task 1.
- Produces: `GauntletScore(green: bool, survived: bool, references_ok: int)`; `score_with_gauntlet(goal, src, config, ref_client, patterns) -> GauntletScore`; `make_scoring_stub(goal_name)`, `make_mining_stub(goal_name)` (clients whose `.messages.parse(...)` returns an `_OraclePair`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calibration_gauntlet.py
from avow.calibration_gauntlet import score_with_gauntlet, GauntletScore
from avow.calibration_benchmark import FAMILY_GOALS, FAMILY_FIXTURES, make_scoring_stub
from avow.config import RunConfig


def _goal(name):
    return next(g for g in FAMILY_GOALS if g.name == name)


def _cfg():
    # small + few references keeps the real subprocess gauntlet fast but still a majority (k=3)
    return RunConfig(gauntlet_references_k=3, gauntlet_examples=25)


def test_correct_variant_survives_the_gauntlet():
    g = _goal("compare_semver")
    s = score_with_gauntlet(g, g.variants["reference"], _cfg(), make_scoring_stub(g.name), patterns=[])
    assert s.green is True and s.survived is True


def test_false_green_survives_empty_but_is_killed_when_seeded():
    g = _goal("compare_semver")
    bug = g.variants["bug_lexical"]
    empty = score_with_gauntlet(g, bug, _cfg(), make_scoring_stub(g.name), patterns=[])
    seeded = score_with_gauntlet(g, bug, _cfg(), make_scoring_stub(g.name),
                                 patterns=["probe where a shorter numeric field meets a longer one"])
    assert empty.green is True and empty.survived is True     # weak references miss the boundary
    assert seeded.survived is False                            # seeded references probe the boundary -> kill


def test_non_green_source_never_reaches_the_gauntlet():
    g = _goal("compare_semver")
    s = score_with_gauntlet(g, "def compare_semver(a, b):\n    return 'oops'\n", _cfg(),
                            make_scoring_stub(g.name), patterns=[])
    assert s.green is False and s.survived is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_calibration_gauntlet.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'avow.calibration_gauntlet'`.

- [ ] **Step 3a: Add the stub builders** to `avow/calibration_benchmark.py`

```python
from types import SimpleNamespace
from avow.oracle import _OraclePair


def _stub_ref_client(reference_src, diff_strong, diff_weak, *, always_strong=False):
    """A stand-in for the oracle's LLM client. It returns `reference_src` plus a diff test whose
    strategy is STRONG (samples the multi-digit boundary) when the reference-generation prompt is
    seeded (run_gauntlet injects the phrase 'known-tricky' when patterns are present) or when
    always_strong is set; otherwise WEAK. Execution still decides survival — this only proposes."""
    class _Stub:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            content = kwargs["messages"][0]["content"]
            strong = always_strong or ("known-tricky" in content)
            po = _OraclePair(reference_code=reference_src, diff_test_code=diff_strong if strong else diff_weak)
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _Stub()


def make_scoring_stub(goal_name):
    f = FAMILY_FIXTURES[goal_name]
    return _stub_ref_client(f.reference_src, f.diff_strong, f.diff_weak)


def make_mining_stub(goal_name):
    # mining deliberately catches the known bug to learn from it -> always strong
    f = FAMILY_FIXTURES[goal_name]
    return _stub_ref_client(f.reference_src, f.diff_strong, f.diff_weak, always_strong=True)
```

- [ ] **Step 3b: Create `avow/calibration_gauntlet.py`**

```python
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from avow.runner import Runner
from avow.gauntlet import run_gauntlet


@dataclass
class GauntletScore:
    green: bool
    survived: bool
    references_ok: int


def score_with_gauntlet(goal, src, config, ref_client, patterns) -> GauntletScore:
    """Write `src` as the solution, check it is green under the goal's suite, and if so run the
    gauntlet (K references differentially fuzzed). A non-green source never reaches the gauntlet."""
    with tempfile.TemporaryDirectory() as sol, tempfile.TemporaryDirectory() as tst:
        (Path(sol) / "lib.py").write_text(src)
        for fn, content in goal.tests.items():
            (Path(tst) / fn).write_text(content)
        green = Runner(Path(sol), Path(tst), config.test_command,
                       timeout=config.test_timeout_seconds).run().is_green
        if not green:
            return GauntletScore(green=False, survived=False, references_ok=0)
        g = run_gauntlet(Path(sol), goal.goal_text, ref_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds, patterns=patterns)
        return GauntletScore(green=True, survived=g.survived, references_ok=g.references_ok)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_calibration_gauntlet.py -q`
Expected: PASS (3 tests). Empty-patterns bug survives (weak), seeded bug is killed (strong), correct survives, non-green skips the gauntlet.

- [ ] **Step 5: Commit**

```bash
git add avow/calibration_gauntlet.py avow/calibration_benchmark.py tests/test_calibration_gauntlet.py
git commit -m "feat: score_with_gauntlet + seeding-aware stub reference clients"
```

---

### Task 3: Leave-one-out seeding + provenance leakage guard

**Files:**
- Modify: `avow/calibration_gauntlet.py`
- Test: `tests/test_calibration_gauntlet.py` (append)

**Interfaces:**
- Consumes: `abstract_counterexample(counterexample, goal, client, model) -> (AttackPattern|None, int, int)` from `avow/coroner.py`; `AttackPattern` from `avow/graveyard.py`; `run_gauntlet`, `make_mining_stub`, `FAMILY_GOALS`, `FAMILY_FIXTURES`.
- Produces: `LeakageError(Exception)`; `assert_no_leakage(patterns, held_out_name) -> None`; `mine_pattern(goal, seed_bug, config, ref_client, coroner_client) -> AttackPattern | None`; `build_seeded_patterns(mine_goals, held_out_name, config, mining_client_for, coroner_client) -> list[AttackPattern]` where `mine_goals` is `list[tuple[CalibrationGoal, str]]` (goal, seed_bug_variant) already excluding the held-out goal.

- [ ] **Step 1: Write the failing test (append)**

```python
from avow.calibration_gauntlet import (assert_no_leakage, LeakageError, build_seeded_patterns)
from avow.graveyard import AttackPattern
from types import SimpleNamespace


def _coroner_stub(category="numeric-boundary", desc="probe the numeric-vs-lexical boundary"):
    class _C:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            po = AttackPattern(category=category, description=desc, origin_goal="", example_input="x")
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def test_leakage_guard_rejects_a_pattern_mined_from_the_held_out_goal():
    good = [AttackPattern(category="c", description="d", origin_goal="max_version", example_input="x")]
    assert_no_leakage(good, "compare_semver")          # different origin -> fine
    leak = [AttackPattern(category="c", description="d", origin_goal="compare_semver", example_input="x")]
    try:
        assert_no_leakage(leak, "compare_semver")
        assert False, "expected LeakageError"
    except LeakageError:
        pass


def test_build_seeded_patterns_is_leave_one_out_and_stamps_provenance():
    cfg = RunConfig(gauntlet_references_k=3, gauntlet_examples=25)
    held = "compare_semver"
    mine_goals = [(g, "bug_lexical") for g in FAMILY_GOALS if g.name != held]
    pats = build_seeded_patterns(mine_goals, held, cfg, lambda g: make_mining_stub(g.name), _coroner_stub())
    assert pats and all(isinstance(p, AttackPattern) for p in pats)
    origins = {p.origin_goal for p in pats}
    assert held not in origins                          # never mined from the held-out goal
    assert origins <= {"max_version", "sort_versions", "is_newer"}
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_calibration_gauntlet.py -q`
Expected: FAIL with `ImportError: cannot import name 'assert_no_leakage'`.

- [ ] **Step 3: Add the seeding + guard** to `avow/calibration_gauntlet.py`

```python
from avow.coroner import abstract_counterexample


class LeakageError(Exception):
    """A seed pattern was mined from the very goal it is about to be tested on."""


def assert_no_leakage(patterns, held_out_name: str) -> None:
    for p in patterns:
        if p.origin_goal == held_out_name:
            raise LeakageError(
                f"seed pattern mined from held-out goal '{held_out_name}' — leave-one-out violated")


def mine_pattern(goal, seed_bug, config, ref_client, coroner_client):
    """Run the gauntlet on `goal`'s known false-green bug to obtain a counterexample, then abstract
    it into a transferable AttackPattern. Provenance is stamped authoritatively (not trusted from
    the LLM) so the leakage guard is reliable."""
    bug_src = goal.variants[seed_bug]
    with tempfile.TemporaryDirectory() as sol:
        (Path(sol) / "lib.py").write_text(bug_src)
        g = run_gauntlet(Path(sol), goal.goal_text, ref_client, config.gauntlet_model, config.test_command,
                         k=config.gauntlet_references_k, examples=config.gauntlet_examples,
                         timeout=config.test_timeout_seconds, patterns=[])
    if g.counterexample is None:
        return None
    pat, _i, _o = abstract_counterexample(g.counterexample, goal.goal_text, coroner_client, config.coroner_model)
    if pat is None:
        return None
    pat.origin_goal = goal.name
    return pat


def build_seeded_patterns(mine_goals, held_out_name, config, mining_client_for, coroner_client):
    """mine_goals: list of (goal, seed_bug_variant_name), already excluding the held-out goal.
    Mines one pattern per goal, enforces the provenance leakage guard, and dedups by description."""
    pats = []
    for goal, seed_bug in mine_goals:
        p = mine_pattern(goal, seed_bug, config, mining_client_for(goal), coroner_client)
        if p is not None:
            pats.append(p)
    assert_no_leakage(pats, held_out_name)
    seen, out = set(), []
    for p in pats:
        key = p.description.strip().lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_calibration_gauntlet.py -q`
Expected: PASS (5 tests). Guard rejects same-origin, accepts cross-origin; build is leave-one-out with stamped provenance.

- [ ] **Step 5: Commit**

```bash
git add avow/calibration_gauntlet.py tests/test_calibration_gauntlet.py
git commit -m "feat: leave-one-out graveyard seeding + provenance-based leakage guard"
```

---

### Task 4: The proof report — cohorts + n-gated honesty

**Files:**
- Modify: `avow/calibration_gauntlet.py`
- Test: `tests/test_calibration_proof.py`

**Interfaces:**
- Produces: `Cohort(name: str, wrong: int, trusted: int)`; `CalibrationProof(plain: Cohort, survived_empty: Cohort, survived_seeded: Cohort)` with `honesty(min_n: int = 8) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calibration_proof.py
from avow.calibration_gauntlet import Cohort, CalibrationProof


def _proof(plain, se, ss):
    return CalibrationProof(Cohort("plain-green", *plain),
                            Cohort("survived (empty graveyard)", *se),
                            Cohort("survived (seeded graveyard)", *ss))


def test_honesty_prints_raw_counts_always():
    out = _proof((2, 10), (2, 10), (0, 8)).honesty(min_n=8)
    assert "plain-green: 2/10" in out
    assert "survived (seeded graveyard): 0/8" in out


def test_honesty_prints_multiplier_when_n_sufficient():
    # plain 2/10 wrong (0.20), survived-empty 1/10 wrong (0.10) -> 2.0x
    out = _proof((2, 10), (1, 10), (0, 10)).honesty(min_n=8)
    assert "2.0x less likely" in out


def test_honesty_suppresses_multiplier_below_min_n():
    out = _proof((1, 4), (0, 3), (0, 3)).honesty(min_n=8)
    assert "insufficient n" in out
    assert "less likely" not in out


def test_honesty_reports_seeded_vs_empty_catch():
    out = _proof((2, 10), (2, 10), (0, 8)).honesty(min_n=8)
    assert "seeded vs empty" in out and "0 vs 2" in out
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_calibration_proof.py -q`
Expected: FAIL with `ImportError: cannot import name 'Cohort'`.

- [ ] **Step 3: Add the report** to `avow/calibration_gauntlet.py`

```python
@dataclass
class Cohort:
    name: str
    wrong: int
    trusted: int


@dataclass
class CalibrationProof:
    plain: Cohort
    survived_empty: Cohort
    survived_seeded: Cohort

    def honesty(self, min_n: int = 8) -> str:
        lines = [f"{c.name}: {c.wrong}/{c.trusted} wrong-when-trusted (n={c.trusted})"
                 for c in (self.plain, self.survived_empty, self.survived_seeded)]
        p, e = self.plain, self.survived_empty
        if p.trusted >= min_n and e.trusted >= min_n and p.wrong > 0:
            pr, er = p.wrong / p.trusted, e.wrong / e.trusted
            if er > 0:
                lines.append(f"survivors are {pr / er:.1f}x less likely to be wrong than a plain green")
            else:
                lines.append(f"survivors had zero wrong-when-trusted (plain: {pr:.0%})")
        else:
            lines.append(f"insufficient n for a multiplier (need >={min_n}, got "
                         f"plain={p.trusted}, survived={e.trusted}) — raw counts only")
        lines.append(f"seeded vs empty wrong-when-trusted: {self.survived_seeded.wrong} vs {e.wrong}")
        return "\n".join(lines)
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_calibration_proof.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add avow/calibration_gauntlet.py tests/test_calibration_proof.py
git commit -m "feat: CalibrationProof cohorts + n-gated honesty report"
```

---

### Task 5: Orchestration — `run_calibration_proof`

**Files:**
- Modify: `avow/calibration_gauntlet.py`
- Test: `tests/test_calibration_proof.py` (append)

**Interfaces:**
- Consumes: `_evaluate_variant(goal, src, config, oracle_client) -> CalibrationRow`, `CalibrationReport` from `avow/calibration.py`; `score_with_gauntlet`, `build_seeded_patterns` (Tasks 2-3).
- Produces: `ProofClients(scoring_for, mining_for, coroner, oracle)` (a dataclass of callables/clients; `scoring_for` and `mining_for` are `goal -> client`); `seed_bug_for` is `goal -> variant_name`; `run_calibration_proof(goals, seed_bug_for, config, clients, *, min_n=8, use_oracle=False, with_seed=True) -> CalibrationProof`.

- [ ] **Step 1: Write the failing test (append)**

```python
from avow.calibration_gauntlet import run_calibration_proof, ProofClients
from avow.calibration_benchmark import FAMILY_GOALS, make_scoring_stub, make_mining_stub
from avow.config import RunConfig
from types import SimpleNamespace
from avow.graveyard import AttackPattern


def _coroner_stub():
    class _C:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            po = AttackPattern(category="numeric-boundary",
                               description="probe where a shorter numeric field meets a longer one",
                               origin_goal="", example_input="x")
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()


def test_run_proof_seeded_catches_more_false_greens_than_empty():
    goals = [g for g in FAMILY_GOALS if g.name in ("compare_semver", "max_version")]
    cfg = RunConfig(gauntlet_references_k=3, gauntlet_examples=25)
    clients = ProofClients(scoring_for=lambda g: make_scoring_stub(g.name),
                           mining_for=lambda g: make_mining_stub(g.name),
                           coroner=_coroner_stub(), oracle=None)
    proof = run_calibration_proof(goals, lambda g: "bug_lexical", cfg, clients, min_n=1, with_seed=True)
    # each goal contributes one false-green (bug_lexical) that is trusted-but-wrong under the suite
    assert proof.plain.wrong >= 2
    # the empty (weak) gauntlet misses them; the seeded (strong) gauntlet kills them
    assert proof.survived_seeded.wrong < proof.survived_empty.wrong
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_calibration_proof.py::test_run_proof_seeded_catches_more_false_greens_than_empty -q`
Expected: FAIL with `ImportError: cannot import name 'run_calibration_proof'`.

- [ ] **Step 3: Add the orchestration** to `avow/calibration_gauntlet.py`

```python
from avow.calibration import _evaluate_variant, CalibrationReport


@dataclass
class ProofClients:
    scoring_for: object    # goal -> reference client used when scoring a variant's gauntlet
    mining_for: object     # goal -> reference client used when mining a seed pattern
    coroner: object        # client for abstract_counterexample (or None)
    oracle: object         # client for the oracle floor (or None)


def run_calibration_proof(goals, seed_bug_for, config, clients, *, min_n=8, use_oracle=False,
                          with_seed=True) -> CalibrationProof:
    trusted_of = CalibrationReport([], config.confidence_threshold)._trusted
    plain = Cohort("plain-green", 0, 0)
    survived_empty = Cohort("survived (empty graveyard)", 0, 0)
    survived_seeded = Cohort("survived (seeded graveyard)", 0, 0)

    for g in goals:
        for vname, src in g.variants.items():
            row = _evaluate_variant(g, src, config, clients.oracle)
            row.variant = vname
            if not trusted_of(row, use_oracle):
                continue
            plain.trusted += 1
            plain.wrong += int(not row.correct)

            empty = score_with_gauntlet(g, src, config, clients.scoring_for(g), patterns=[])
            if empty.survived:
                survived_empty.trusted += 1
                survived_empty.wrong += int(not row.correct)

            if with_seed:
                mine_goals = [(og, seed_bug_for(og)) for og in goals if og.name != g.name]
                pats = build_seeded_patterns(mine_goals, g.name, config, clients.mining_for, clients.coroner)
                seeded = score_with_gauntlet(g, src, config, clients.scoring_for(g),
                                             patterns=[p.description for p in pats])
                if seeded.survived:
                    survived_seeded.trusted += 1
                    survived_seeded.wrong += int(not row.correct)

    return CalibrationProof(plain, survived_empty, survived_seeded)
```

Note on `_trusted` reuse: `CalibrationReport([], threshold)._trusted(row, use_oracle)` reuses the exact trusted definition (green + confidence ≥ threshold + optional oracle floor) so the proof and the existing report never drift.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest tests/test_calibration_proof.py -q`
Expected: PASS (5 tests). Seeded kills the false-greens the empty gauntlet missed, so `survived_seeded.wrong < survived_empty.wrong`.

- [ ] **Step 5: Commit**

```bash
git add avow/calibration_gauntlet.py tests/test_calibration_proof.py
git commit -m "feat: run_calibration_proof — three-cohort false-high-confidence over plain/survived/seeded"
```

---

### Task 6: CLI — `avow calibrate --gauntlet [--llm] [--seed]`

**Files:**
- Modify: `avow/cli.py`
- Test: `tests/test_cli_calibrate.py` (create if absent)

**Interfaces:**
- Consumes: `run_calibration_proof`, `ProofClients` (Task 5); `DEFAULT_GOALS`, `FAMILY_GOALS`, `make_scoring_stub`, `make_mining_stub` from the benchmark.
- Produces: the extended `_cmd_calibrate` behavior and subparser flags. The CLI is the only place allowed to import both the engine and the benchmark and wire them together.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_calibrate.py
import avow.cli as cli


def test_calibrate_gauntlet_stub_mode_prints_cohorts(capsys):
    rc = cli.main(["calibrate", "--gauntlet", "--seed"])   # no --llm -> deterministic stub mode
    out = capsys.readouterr().out
    assert rc == 0
    assert "plain-green:" in out
    assert "survived (empty graveyard):" in out
    assert "survived (seeded graveyard):" in out
    assert "STUB MODE" in out                                # honest label: mechanism, not real numbers
    assert "not a proof of correctness" in out.lower()       # retained disclaimer
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest tests/test_cli_calibrate.py -q`
Expected: FAIL (`--gauntlet` unrecognized, or no cohort output).

- [ ] **Step 3: Extend `_cmd_calibrate`** in `avow/cli.py`

Find `_cmd_calibrate` (around line 341). Add, at the top of the function, a branch for `--gauntlet` before the existing reliability path:

```python
    if getattr(args, "gauntlet", False):
        return _cmd_calibrate_gauntlet(args)
```

Then add the new handler next to it:

```python
def _cmd_calibrate_gauntlet(args) -> int:
    from avow.calibration_gauntlet import run_calibration_proof, ProofClients
    from avow.calibration_benchmark import (DEFAULT_GOALS, FAMILY_GOALS,
                                            make_scoring_stub, make_mining_stub)

    config = RunConfig.from_yaml(args.config) if args.config else RunConfig()
    if args.llm:
        import anthropic
        client = anthropic.Anthropic()
        goals = DEFAULT_GOALS + FAMILY_GOALS
        clients = ProofClients(scoring_for=lambda g: client, mining_for=lambda g: client,
                               coroner=client, oracle=client)
        label = f"n={sum(len(g.variants) for g in goals)}, LLM references, single run"
    else:
        goals = FAMILY_GOALS   # stubs only cover the family; DEFAULT_GOALS need real references
        clients = ProofClients(scoring_for=lambda g: make_scoring_stub(g.name),
                               mining_for=lambda g: make_mining_stub(g.name),
                               coroner=_stub_coroner(), oracle=None)
        label = "STUB MODE — deterministic mechanism demonstration, not real references"

    proof = run_calibration_proof(goals, lambda g: "bug_lexical", config, clients,
                                  min_n=8, use_oracle=args.llm, with_seed=args.seed)
    print(f"calibration proof ({label}):")
    print(proof.honesty(min_n=8))
    print("note: 'survived' means it agreed with independent references across a fuzzed space — "
          "not a proof of correctness.")
    return 0


def _stub_coroner():
    from types import SimpleNamespace
    from avow.graveyard import AttackPattern

    class _C:
        @property
        def messages(self):
            return self

        def parse(self, *, output_format, **kwargs):
            po = AttackPattern(category="numeric-boundary",
                               description="probe where a shorter numeric field meets a longer one",
                               origin_goal="", example_input="x")
            return SimpleNamespace(parsed_output=po, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return _C()
```

- [ ] **Step 4: Add the subparser flags.** Find the `cal_p = sub.add_parser("calibrate", ...)` line (around line 456) and add:

```python
    cal_p.add_argument("--gauntlet", action="store_true",
                       help="run the survival-gauntlet calibration proof (plain vs survived vs seeded)")
    cal_p.add_argument("--seed", action="store_true",
                       help="include the seeded-graveyard cohort (leave-one-out)")
```

Confirm `cal_p` already has `--llm` and `--config` (it does — used by the existing reliability path). If `--llm` is missing, add `cal_p.add_argument("--llm", action="store_true")`.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest tests/test_cli_calibrate.py -q && avow calibrate --gauntlet --seed | head`
Expected: PASS; the command prints the three cohorts, the honesty line, the STUB MODE label, and the disclaimer.

- [ ] **Step 6: Full-suite gate**

Run: `python -m pytest -q`
Expected: PASS, 0 warnings.

- [ ] **Step 7: Commit**

```bash
git add avow/cli.py tests/test_cli_calibrate.py
git commit -m "feat: avow calibrate --gauntlet/--llm/--seed — the survival-instinct calibration proof"
```

---

## Manual validation (after Task 6, needs ANTHROPIC_API_KEY)

Run `avow calibrate --gauntlet --seed --llm`. Confirm: the three cohorts print with real reference counts; the label reads `LLM references, single run`; and if any cohort's `trusted < 8`, the multiplier line reads `insufficient n` rather than inventing a number. This is a single labeled run, not a distribution — the honesty guard is what keeps it from overclaiming.

## Out of scope (backlog)

- Embedding/semantic pattern retrieval (keyword/tag only, matches B).
- Cross-provider references (OpenRouter).
- Multi-run distributions / confidence intervals under `--llm`.
