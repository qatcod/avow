from __future__ import annotations

from pydantic import BaseModel


class Idea(BaseModel):
    description: str
    verifier: str
    objective: bool
    risk: str  # "low" | "high"


class _IdeaSet(BaseModel):
    ideas: list[Idea]


_IDEATOR_PROMPT = """\
You are improving a software artifact. Given its GOAL and the tests that already \
exist, propose up to {n} concrete NEXT features or improvements — ranked best-first \
— that would make it genuinely better or more complete. For each, give:
- description: the feature/improvement, concretely.
- verifier: how it would be checked — ideally an objective behavioral test.
- objective: true if the verifier is an objective pass/fail test (not a matter of taste).
- risk: "low" if it is a safe, well-scoped addition; "high" if it is broad, ambiguous, \
or could break existing behavior.

Prefer improvements that are objectively verifiable and not already covered by the \
existing tests. Do NOT propose things the tests already check.

GOAL:
{goal}

EXISTING TESTS:
{current_tests}
"""


def propose_ideas(goal: str, current_tests: str, client, model: str, n: int):
    if n <= 0 or client is None:
        return [], 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=4000,
        messages=[{"role": "user", "content": _IDEATOR_PROMPT.format(
            n=n, goal=goal, current_tests=current_tests)}],
        output_format=_IdeaSet,
    )
    usage = response.usage
    return (
        list(response.parsed_output.ideas[:n]),
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
