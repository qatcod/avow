from __future__ import annotations

from pydantic import BaseModel

from forge.examiner import TestFile


class _PropertySet(BaseModel):
    tests: list[TestFile]


_PROPERTY_PROMPT = """\
You are writing property-based (metamorphic) tests with the Hypothesis library. Given \
the goal below, write exactly {n} pytest test files, each using `@given(...)` from \
`hypothesis` to assert an INVARIANT or METAMORPHIC RELATION that must hold for ALL valid \
inputs — round-trips (e.g. `decode(encode(x)) == x`), idempotence, commutativity / \
associativity, ordering / monotonicity, length / permutation preservation, or known \
algebraic laws — rather than specific input/output examples.

Rules:
- Each file imports the implementation from a top-level module (e.g. `from lib import f`) \
and `from hypothesis import given, strategies as st`.
- Use `@given(...)` with strategies appropriate to the input types implied by the goal.
- Assert relations any CORRECT implementation must satisfy; do NOT assert a specific \
output value unless it is a true invariant.
- Each file path is a bare filename like `test_prop_<area>.py`.

GOAL:
{goal}
"""


def generate_property_tests(goal: str, client, model: str, n: int) -> tuple[list[TestFile], int, int]:
    if n <= 0 or client is None:
        return [], 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": _PROPERTY_PROMPT.format(n=n, goal=goal)}],
        output_format=_PropertySet,
    )
    usage = response.usage
    return (
        list(response.parsed_output.tests[:n]),
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
