from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel


class _InferredGoal(BaseModel):
    inferred_goal: str


_BACKTRANSLATE_PROMPT = """\
You are reverse-engineering a specification from its tests. Below is a test suite and \
nothing else. Infer, as precisely as you can, what the code under test is supposed to \
do — the goal the author was testing toward. Write the inferred goal as a clear, \
self-contained description. Do not critique the tests; just state what goal they \
appear to verify.

TEST SUITE:
{tests}
"""


def back_translate(test_sources: str, client, model: str):
    response = client.messages.parse(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": _BACKTRANSLATE_PROMPT.format(tests=test_sources)}],
        output_format=_InferredGoal,
    )
    usage = response.usage
    return (
        response.parsed_output.inferred_goal,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )


class IntentMatch(BaseModel):
    score: float
    divergences: list[str]


_JUDGE_PROMPT = """\
Compare two descriptions of a programming goal: the ORIGINAL goal, and a goal that was \
INFERRED purely from a test suite (whoever inferred it never saw the original). Rate how \
well they match on a 0.0-1.0 scale (1.0 = the inferred goal captures the original's \
intent exactly; lower = the tests drifted from, missed, or invented requirements). List \
the concrete divergences: requirements in the original that the inferred goal misses, or \
requirements the inferred goal adds that the original never asked for.

ORIGINAL GOAL:
{original}

INFERRED-FROM-TESTS GOAL:
{inferred}
"""


def judge_intent_match(original_goal: str, inferred_goal: str, client, model: str):
    response = client.messages.parse(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": _JUDGE_PROMPT.format(
            original=original_goal, inferred=inferred_goal)}],
        output_format=IntentMatch,
    )
    usage = response.usage
    return (
        response.parsed_output,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )


@dataclass
class IntentResult:
    score: float
    inferred_goal: str
    divergences: list[str]
    input_tokens: int
    output_tokens: int


def run_intent_check(goal: str, frozen_tests_dir, client, model: str) -> IntentResult:
    frozen_tests_dir = Path(frozen_tests_dir)
    parts = []
    for f in sorted(frozen_tests_dir.glob("test_*.py")):
        parts.append(f"# ===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    test_sources = "\n\n".join(parts)

    inferred, in1, out1 = back_translate(test_sources, client, model)
    match, in2, out2 = judge_intent_match(goal, inferred, client, model)
    return IntentResult(
        score=match.score,
        inferred_goal=inferred,
        divergences=match.divergences,
        input_tokens=in1 + in2,
        output_tokens=out1 + out2,
    )
