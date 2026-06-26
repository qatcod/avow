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
