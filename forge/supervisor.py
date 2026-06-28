from __future__ import annotations

from pydantic import BaseModel


class SupervisorVerdict(BaseModel):
    assessment: str
    recommendation: str  # "continue" | "redirect" | "escalate" | "abort"
    escalate: bool


_SUPERVISOR_PROMPT = """\
You are the Supervisor of an autonomous build loop. The Builder has been trying to make a \
frozen test suite pass and is now PLATEAUING (no recent improvement). Read the GOAL and the \
recent attempt trajectory, then judge whether the run is recoverable.

Emit:
- assessment: a concise diagnosis of what's going wrong; if you recommend "redirect", make \
this the concrete guidance the Builder should follow next.
- recommendation: exactly one of "continue" (plateau looks temporary, keep going), \
"redirect" (the Builder is on the wrong track — your assessment is handed to it as \
guidance), "escalate" (a human should look), or "abort" (the goal looks unreachable as stated).
- escalate: true if a human should be pulled in.

GOAL:
{goal}

RECENT ATTEMPTS (oldest first):
{trajectory}
"""


def _format_history(history) -> str:
    lines = []
    for h in history[-8:]:
        failing = ", ".join(list(getattr(h, "failing", []))[:5])
        lines.append(f"iter {h.iteration}: score={h.score:.2f} green={h.is_green} "
                     f"plan={(h.plan or '')[:120]} failing=[{failing}]")
    return "\n".join(lines)


def review_trajectory(goal, history, client, model) -> tuple:
    if client is None:
        return None, 0, 0
    response = client.messages.parse(
        model=model,
        max_tokens=2000,
        messages=[{"role": "user", "content": _SUPERVISOR_PROMPT.format(
            goal=goal, trajectory=_format_history(history))}],
        output_format=SupervisorVerdict,
    )
    usage = response.usage
    return (
        response.parsed_output,
        getattr(usage, "input_tokens", 0),
        getattr(usage, "output_tokens", 0),
    )
