"""Explicit per-run execution state for the planner trace."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.events.bus import RunStream

PlannerMode = Literal["plan", "execute"]


@dataclass
class AgentMode:
    """One run's plan/execute state; execution is a one-way, one-time transition."""

    current: PlannerMode = "plan"
    _transitioned: bool = False

    async def transition_to_execute(self, stream: RunStream) -> None:
        if self._transitioned or self.current != "plan":
            raise RuntimeError("agent mode can transition from plan to execute only once")
        await stream.emit("mode_transition", {"from": "plan", "to": "execute"})
        self.current = "execute"
        self._transitioned = True
