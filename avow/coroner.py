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
