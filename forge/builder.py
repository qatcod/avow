from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from forge.scoring import FailureInfo

_PROMPT = """\
You are an autonomous software builder working inside the current directory.

Your goal:
{goal}

A hidden, frozen acceptance-test suite grades your work. You CANNOT see or edit the \
tests, and any file you place under a `tests/` directory will be discarded before \
grading. Edit only the implementation/solution code in this directory.

{failures_block}

Implement or fix the code so the acceptance tests pass. Make the smallest change that \
could plausibly work. Do not add features, abstractions, or error handling beyond what \
the goal requires.
"""


@dataclass
class BuilderOutcome:
    plan: str
    cost_usd: float
    raw: dict


class Builder:
    def __init__(self, model: str, runner=subprocess.run) -> None:
        self.model = model
        self.runner = runner

    def attempt(self, solution_dir: Path, goal: str, failures: list[FailureInfo]) -> BuilderOutcome:
        prompt = _PROMPT.format(goal=goal, failures_block=self._failures_block(failures))
        cmd = [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--dangerously-skip-permissions",
            "--model", self.model,
        ]
        proc = self.runner(cmd, cwd=Path(solution_dir), capture_output=True, text=True)
        return self._parse(proc)

    @staticmethod
    def _failures_block(failures: list[FailureInfo]) -> str:
        if not failures:
            return "This is the first attempt; no failures yet."
        lines = ["The previous attempt failed these tests — fix them:"]
        for f in failures:
            lines.append(f"- {f.nodeid}: {f.message}")
        return "\n".join(lines)

    @staticmethod
    def _parse(proc: subprocess.CompletedProcess) -> BuilderOutcome:
        try:
            data = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            return BuilderOutcome(
                plan=(proc.stdout or proc.stderr or "").strip(), cost_usd=0.0, raw={}
            )
        return BuilderOutcome(
            plan=str(data.get("result", "")),
            cost_usd=float(data.get("total_cost_usd", 0.0)),
            raw=data,
        )
