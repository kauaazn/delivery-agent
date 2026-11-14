"""A clock you move by hand, for tests and evals: order statuses depend on elapsed time."""
from __future__ import annotations


class ManualClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now += minutes * 60
