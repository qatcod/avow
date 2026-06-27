from __future__ import annotations

from pydantic import BaseModel


class _OraclePair(BaseModel):
    reference_code: str
    diff_test_code: str


_ORACLE_PROMPT = """\
You are building a DIFFERENTIAL ORACLE for a piece of software. Given the GOAL, produce \
two things:

1. reference_code: the SIMPLEST, most OBVIOUSLY-CORRECT implementation of the goal — \
prioritize clarity and correctness over speed or elegance (a naive, slow, plainly-right \
version). It must expose the SAME public function(s) as the goal implies.

2. diff_test_code: a pytest module using the Hypothesis library that imports the clever \
implementation as `from lib import <name> as _sol` and your reference as \
`from ref import <name> as _ref`, then uses `@given(...)` from `hypothesis` with \
strategies matching the goal's input types to assert `_sol(x) == _ref(x)` for all inputs. \
One `@given` test per public function. Do not import anything else from lib/ref.

The two implementations are written independently so that a disagreement reveals a bug in \
one of them. Make the reference genuinely independent (a different, simpler approach).

GOAL:
{goal}
"""


def generate_oracle(goal: str, client, model: str) -> tuple[_OraclePair | None, int, int]:
    if client is None:
        return None, 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": _ORACLE_PROMPT.format(goal=goal)}],
        output_format=_OraclePair,
    )
    usage = response.usage
    return (
        response.parsed_output,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
