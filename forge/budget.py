from __future__ import annotations

from dataclasses import dataclass, field

# (input $/1M, output $/1M) — from the Anthropic pricing table.
PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
}


@dataclass
class Budget:
    max_cost_usd: float
    max_iterations: int
    max_wall_seconds: int
    started_at: float | None = None
    _spent_usd: float = field(default=0.0, init=False, repr=False)
    _iterations: int = field(default=0, init=False, repr=False)

    @property
    def spent_usd(self) -> float:
        return self._spent_usd

    @property
    def iterations(self) -> int:
        return self._iterations

    def charge_tokens(self, model: str, input_tokens: int, output_tokens: int) -> None:
        rate = PRICES.get(model)
        if rate is None:
            return
        in_rate, out_rate = rate
        self._spent_usd += (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000

    def charge_usd(self, amount: float) -> None:
        self._spent_usd += amount

    def tick_iteration(self) -> None:
        self._iterations += 1

    def exhausted(self, now: float) -> str | None:
        if self._spent_usd >= self.max_cost_usd:
            return "cost"
        if self._iterations >= self.max_iterations:
            return "iterations"
        if self.started_at is not None and (now - self.started_at) >= self.max_wall_seconds:
            return "wall_clock"
        return None
