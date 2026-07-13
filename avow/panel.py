from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from avow.backtranslation import back_translate, judge_intent_match


@dataclass
class PanelResult:
    mean: float
    scores: dict
    agreement: float


def aggregate_panel(scores: dict) -> PanelResult:
    if not scores:
        return PanelResult(mean=0.0, scores={}, agreement=1.0)
    vals = list(scores.values())
    mean = sum(vals) / len(vals)
    agreement = 1.0 if len(vals) <= 1 else max(0.0, 1.0 - (max(vals) - min(vals)))
    return PanelResult(mean=mean, scores=dict(scores), agreement=agreement)


@dataclass
class PanelIntentResult:
    score: float
    agreement: float
    inferred_goal: str
    divergences: list
    usage: list  # list[tuple[model, input_tokens, output_tokens]]


def panel_intent_check(goal: str, frozen_tests_dir, client, models: list) -> PanelIntentResult:
    frozen_tests_dir = Path(frozen_tests_dir)
    parts = []
    for f in sorted(frozen_tests_dir.glob("test_*.py")):
        parts.append(f"# ===== {f.name} =====\n{f.read_text(encoding='utf-8')}")
    test_sources = "\n\n".join(parts)

    bt_model = models[0]
    inferred, bt_in, bt_out = back_translate(test_sources, client, bt_model)
    usage = [(bt_model, bt_in, bt_out)]

    scores = {}
    divergences = []
    seen = set()
    for m in models:
        match, j_in, j_out = judge_intent_match(goal, inferred, client, m)
        scores[m] = match.score
        usage.append((m, j_in, j_out))
        for d in match.divergences:
            if d not in seen:
                seen.add(d)
                divergences.append(d)

    panel = aggregate_panel(scores)
    return PanelIntentResult(
        score=panel.mean,
        agreement=panel.agreement,
        inferred_goal=inferred,
        divergences=divergences,
        usage=usage,
    )
