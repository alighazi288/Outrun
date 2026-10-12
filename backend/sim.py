"""The loop the API and the exporter use: the world as it stood at time t.

    1. Replay clock is at t. DataStore.at(t) returns only what existed by t.
    2. Nowcast: P(fire reaches each cell within 1, 2, 3 h), from satellite detections and
       fire reports.
    3. (The Intake agent has already turned new help requests and fire reports into records via
       POST /requests and POST /reports.)
    4. Risk: priority and rescue deadline per resident.
    5. Router: re-plan routes for the fleet, within the driver-safety rule.
    6. The plan is approved: automatically after the approval delay in the exported replay
       and the evaluation; in the live API only when the manager decides (POST /decisions).
    7. Vehicles move along approved plans and pick people up (backend/replay.py).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from backend.replay import Frame, Replay, world_state
from backend.schemas import Decision, WorldState
from backend.store import DataStore
from engines import TravelTime, plan_routes

StepResult = Frame


class Simulation:
    def __init__(self, store: DataStore, travel: TravelTime | None = None, planner=plan_routes,
                 decisions: Callable[[], list[Decision]] | None = None):
        """decisions: where the manager's decisions come from. None = plans auto-approve."""
        self.store = store
        self.replay = Replay(store, planner=planner, travel=travel, decisions=decisions)

    def invalidate(self) -> None:
        """Call after the data changes (e.g. a new help request or fire report)."""
        self.replay.invalidate()

    def step(self, t: datetime) -> Frame:
        return self.replay.frame_at(t)

    def world_state(self, t: datetime, decisions: list[Decision] | None = None) -> WorldState:
        return world_state(self.step(t), t, self.store.name, decisions or [])
