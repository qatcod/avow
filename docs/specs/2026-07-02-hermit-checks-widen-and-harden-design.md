# Hermit — Widen & Harden the Check Subsystem — Design Spec

**Status:** Approved (2026-07-02). Three incremental extensions to the Verifier Checks subsystem (shipped 2026-07-02, `origin/main` 9a09012). Each follows an established Hermit convention: risky behavior ships dormant behind an opt-in flag; new capability reuses an existing seam (the check-fold, the leash, the expand phase).

Goal of the batch: make the verifier *wider* (measure numbers, not just pass/fail), *harder to cheat* (strip builder-loosened config), and *self-extending* (the Ideator proposes new gates). This pushes Hermit further past "code-with-unit-tests" toward "drive any verifiable product to perfect."

---

## Feature A — Metric-threshold checks

Today a check passes iff its command exits 0. Many quality gates are really a **number vs a budget**: bundle size ≤ 500 KB, coverage ≥ 90 %, p95 latency ≤ 200 ms, cyclomatic complexity ≤ 10. Feature A adds that mode.

**The model.** A check may carry `max` and/or `min` (numbers). If **either** is present, the check is a **metric check**:
1. Run the command; it must **succeed (exit 0)** — a non-zero exit is a **failed** check (a measurement that crashed cannot certify a budget). This also stops a crashing command's stderr traceback from supplying a false metric.
2. Parse a number from **stdout only**: by default the **last** token matching a number (with thousands-separator and scientific-notation support, and without misreading hyphenated tokens like `utf-8` as negatives); an optional `pattern` (regex) overrides — if a capture group participated, group 1 is used, else the whole match. The default parser is best-effort; non-trivial output should use an explicit `pattern`.
3. Pass iff `min ≤ value ≤ max` (inclusive) for whichever bound(s) are given. Bounds are coerced to float; a present-but-non-numeric bound (e.g. `max: "abc"`) or a metric check with no numeric bound is a **misconfigured** (failed) check.
4. If the command errors (OSError/timeout), exits non-zero, or **no number** can be parsed → **failed** check with an honest detail. Never a crash.

A check with neither `max` nor `min` is an **exit-code check** (unchanged from today).

**Config shape:** `{name, command, max?: float, min?: float, pattern?: str}`. Example:
```yaml
checks:
  - name: bundle-size
    command: ["wc", "-c", "dist/app.js"]
    max: 500000
  - name: coverage
    command: ["python", "-c", "print(94.2)"]
    min: 90
```

`CheckResult` is unchanged (`name/passed/detail`); the metric and the breached bound go in `detail` on failure (`metric 640000 > max 500000`).

---

## Feature B — Stronger check anti-cheat (ships dormant)

The honest limitation of checks: they run on the solution dir and the Builder sees the failures, so a determined Builder could silence a lint/type check by loosening its **tool config** (`.ruff.toml`, `mypy.ini`, …) rather than fixing the code. Feature B closes that hole — **opt-in, off by default**.

**New setting:** `strip_check_config: bool = False` (dormant, like `adjudicate_enabled` / `supervisor_enabled`).

**When enabled:** `run_checks` runs the checks in **one ephemeral copy** of the solution dir (shared by all checks in the call; mirroring how `Runner` grades tests in a clean copy) with builder-authorable tool-config files removed **at every depth** (nested `src/.ruff.toml` too) before the commands run:
`.ruff.toml`, `ruff.toml`, `.flake8`, `setup.cfg`, `tox.ini`, `mypy.ini`, `.mypy.ini`, `.pylintrc`, `.isort.cfg`.

The copy tolerates broken symlinks/special files; if the sandbox can't be built at all, **every check fails** (with a detail) rather than crashing the run — preserving the never-crash guarantee. The copy is per-run overhead, so keep the solution dir free of large artifacts when enabling this.

**Deliberately NOT stripped:** `pyproject.toml` — it commonly carries real dependencies and `[tool.*]` a goal legitimately needs; blanket-removing it would break honest projects. This is a documented limitation: a Builder could still weaken a check via `[tool.ruff]` in `pyproject.toml`. Stripping just the `[tool.*]` tables from `pyproject.toml` is a noted future refinement.

**When disabled (default):** checks run in the solution dir exactly as today — **zero behavior change**, provable by the flag guard.

`run_checks(solution_dir, checks, timeout=120, strip_config=False)`; the loop and CLI pass `config.strip_check_config`.

---

## Feature C — Ideator proposes checks (self-extending verifier menu)

The expand phase (`hermit improve`) currently has the **Ideator** propose next *features*, each verified by a **test** the Examiner writes. Feature C lets the Ideator also propose a **check** — a lint/typecheck/quality gate — so Hermit widens its *own* verifier menu as it self-improves.

**Schema:** `Idea` gains `kind: str = "test"` (values `"test" | "check"`) and `check_command: list[str] = []`. The Ideator prompt is extended: it may propose `kind="check"` with a `check_command` (args list) for an automated gate not worth a bespoke test (style, types, a size/complexity budget). A check-idea is **objective** by nature (a command), so the existing **leash** (`select_idea`: auto-pursue objective + low-risk) handles it unchanged.

**Expand-phase branch (`improve`):** when the chosen idea is `kind == "check"` with a non-empty `check_command`:
- append `{"name": f"idea_e{round}", "command": chosen.check_command}` to `config.checks` (in-memory; enforced from the next converge round on) — **no Examiner call, no test written**;
- re-solve (`write_tests=False`) so the new gate must now hold alongside the suite.

A check-idea with an empty `check_command` is not actionable and stops expansion. `kind == "test"` (the default) → existing behavior, untouched.

**Trust boundary (honest framing):** a check-idea's `check_command` is **LLM-authored and executed** by `run_checks` — the *same* untrusted-code-execution boundary Hermit already crosses when the Builder runs `claude`-generated code. The leash (objective + low-risk auto-pursue, else human escalation) governs the idea's **scope/risk**, not the command's **capability**; run `hermit improve` with check-proposals only where you would already trust the Builder. A tool allowlist for auto-pursued check-ideas is a noted future guard.

---

## Testing strategy

- **A (metric):** value under/over `max`; under/over `min`; both bounds; `pattern` extraction with and without a capture group; unparseable output → failed (not crash); a metric check whose command is missing → failed. Exit-code checks still behave as before (regression).
- **B (strip):** with `strip_config=True`, a planted tool-config file is absent when the command runs (proven by a command that exits 0 iff the file exists → flips to fail under strip); with `strip_config=False`, the file is present (unchanged). `pyproject.toml` survives stripping. Loop wires `config.strip_check_config`.
- **C (Ideator):** a fake ideator client returning a `kind="check"` idea → `improve()` appends it to `config.checks` and the next round enforces it (a solution that fails the check does not go green); a `kind="test"` idea → unchanged expand behavior; an empty `check_command` check-idea → skipped.
- Full suite green after each feature; `checks == []` / flags-off paths provably unchanged.

## Out of scope (later)

- Stripping `[tool.*]` tables out of `pyproject.toml` (finer-grained than file removal).
- Sandboxed/network-isolated check execution.
- Rubric / cross-provider-panel checks for subjective quality (needs OpenRouter credits).
- The Ideator proposing *metric* checks with bounds (this batch lets it propose exit-code checks; bounds are a natural follow-up once A lands).
