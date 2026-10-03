"""The replay over time: vehicles follow approved plans, pick people up, and re-plan.

Every replay step t (10 minutes):

1. Move every vehicle forward to t along its approved schedule. A pickup counts at the moment
   the vehicle leaves the stop with the person on board.
2. If no plan is waiting for approval, make a new one:
   - each vehicle keeps the run it is on (its pickups through the next shelter) and drops
     anything planned after that;
   - everyone known, not yet picked up and not on a kept run is planned for;
   - each vehicle becomes available when its current run ends, but never before the approval
     delay, so the plan is still valid when it takes effect.
3. The plan takes effect `approval_delay_min` later. Here it is auto-approved (the evaluation
   needs that); the live demo still waits for a person. Until it takes effect, vehicles finish
   their current run and wait. With a delay longer than one step, plans are made less often,
   which is exactly the cost of slow approval.

Only data that existed at time t is used (DataStore.at(t)).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.assumptions import APPROVAL_DELAY_MIN, UNLOAD_MIN
from backend.schemas import (
    Decision,
    FireOutlook,
    Plan,
    ResidentRisk,
    Route,
    Vehicle,
    WorldState,
)
from backend.store import DataStore, Snapshot
from engines import StraightLineTravel, TravelTime, nowcast, plan_routes, prioritize

LatLon = tuple[float, float]


@dataclass
class Leg:
    """One approved stop and when the vehicle sets off for it, arrives, and leaves."""

    stop: str
    kind: str  # "pickup" | "dropoff"
    pos: LatLon
    leave_prev: datetime
    arrive: datetime
    depart: datetime


@dataclass
class Track:
    vehicle: Vehicle
    pos: LatLon  # the last place the vehicle finished a stop (or its depot)
    legs: list[Leg] = field(default_factory=list)  # approved stops not yet finished


@dataclass
class _Pending:
    plan: Plan
    takes_effect: datetime
    starts: dict[str, datetime]  # vehicle -> when the plan assumed it is free


@dataclass
class ReplayState:
    t: datetime
    tracks: dict[str, Track]
    picked_up: dict[str, datetime] = field(default_factory=dict)
    pending: _Pending | None = None
    last_plan: Plan | None = None
    last_plan_effect: datetime | None = None


@dataclass(frozen=True)
class Frame:
    """Everything known and decided at time t."""

    snapshot: Snapshot
    outlook: list[FireOutlook]
    risks: list[ResidentRisk]
    plan: Plan
    plan_takes_effect_at: datetime | None
    vehicles: list[Vehicle]
    schedule: list[Route]
    picked_up: dict[str, datetime]


class Replay:
    def __init__(
        self,
        store: DataStore,
        planner=plan_routes,
        travel: TravelTime | None = None,
        approval_delay_min: float = APPROVAL_DELAY_MIN,
    ):
        self.store = store
        self.planner = planner
        self.travel = travel or StraightLineTravel()
        self.delay = timedelta(minutes=approval_delay_min)
        self.clock = store.make_clock()
        self.invalidate()

    def invalidate(self) -> None:
        """Forget everything computed. Call after the data changes (a new help request)."""
        start = self.clock.start
        tracks = {v.id: Track(v, (v.lat, v.lon)) for v in self.store.vehicles}
        self._states: list[tuple[datetime, ReplayState]] = []
        self._frames: dict[datetime, Frame] = {}
        self._initial = ReplayState(t=start, tracks=tracks)

    # -- public ------------------------------------------------------------------------------

    def run(self) -> list[Frame]:
        """Every step of the night, in order."""
        return [self.frame_at(t) for t in self.clock.times()]

    def frame_at(self, t: datetime) -> Frame:
        if t in self._frames:
            return self._frames[t]
        self._compute_until(t)
        if t in self._frames:
            return self._frames[t]
        # Between steps (or outside the window): replay from the last step on a copy.
        before = [s for when, s in self._states if when <= t]
        state = copy.deepcopy(before[-1] if before else self._initial)
        return self._step(state, t)

    # -- the loop ------------------------------------------------------------------------------

    def _compute_until(self, t: datetime) -> None:
        state = copy.deepcopy(self._states[-1][1]) if self._states else copy.deepcopy(self._initial)
        for when in self.clock.times():
            if when > t:
                break
            if when in self._frames:
                continue
            self._frames[when] = self._step(state, when)
            self._states.append((when, copy.deepcopy(state)))

    def _step(self, state: ReplayState, t: datetime) -> Frame:
        self._advance_to(state, t)
        snap = self.store.at(t)
        outlook = nowcast(snap.detections, snap.wind, self.store.cells, t, snap.reports)
        if state.pending is None:
            self._plan(state, snap, outlook, t)
            if state.pending.takes_effect <= t:
                self._activate(state)
        committed = {leg.stop for tr in state.tracks.values() for leg in tr.legs}
        open_residents = [
            r for r in snap.residents if r.id not in state.picked_up and r.id not in committed
        ]
        risks = prioritize(open_residents, outlook, t)
        return Frame(
            snapshot=snap,
            outlook=outlook,
            risks=risks,
            plan=state.last_plan,
            plan_takes_effect_at=state.last_plan_effect,
            vehicles=[self._vehicle_now(tr, t) for tr in state.tracks.values()],
            schedule=[
                Route(vehicle=v, stops=[leg.stop for leg in tr.legs],
                      eta_min=[round(max((leg.arrive - t).total_seconds() / 60, 0), 1)
                               for leg in tr.legs])
                for v, tr in state.tracks.items() if tr.legs
            ],
            picked_up=dict(state.picked_up),
        )

    def _advance_to(self, state: ReplayState, t: datetime) -> None:
        if state.pending and state.pending.takes_effect <= t:
            self._move(state, state.pending.takes_effect)
            self._activate(state)
        self._move(state, t)

    def _move(self, state: ReplayState, t: datetime) -> None:
        for tr in state.tracks.values():
            while tr.legs and tr.legs[0].depart <= t:
                leg = tr.legs.pop(0)
                if leg.kind == "pickup":
                    state.picked_up[leg.stop] = leg.depart
                tr.pos = leg.pos
        state.t = max(state.t, t)

    def _plan(self, state: ReplayState, snap: Snapshot, outlook: list[FireOutlook],
              t: datetime) -> None:
        # Each vehicle keeps the run it is on; anything after that is re-planned.
        for tr in state.tracks.values():
            kept: list[Leg] = []
            if tr.legs and tr.legs[0].leave_prev <= t:
                for leg in tr.legs:
                    kept.append(leg)
                    if leg.kind == "dropoff":
                        break
            tr.legs = kept
        committed = {leg.stop for tr in state.tracks.values() for leg in tr.legs}

        vehicles, starts = [], {}
        for v_id, tr in state.tracks.items():
            free_at, pos = (tr.legs[-1].depart, tr.legs[-1].pos) if tr.legs else (t, tr.pos)
            start = max(free_at, t + self.delay)
            starts[v_id] = start
            vehicles.append(tr.vehicle.model_copy(update={
                "lat": pos[0], "lon": pos[1],
                "available_in_min": (start - t).total_seconds() / 60,
                "status": "en_route" if tr.legs else "idle",
            }))
        residents = [
            r for r in snap.residents if r.id not in state.picked_up and r.id not in committed
        ]
        risks = prioritize(residents, outlook, t)
        plan = self.planner(risks, residents, vehicles, snap.shelters, outlook, self.travel, t)
        state.pending = _Pending(plan, t + self.delay, starts)
        state.last_plan, state.last_plan_effect = plan, t + self.delay

    def _activate(self, state: ReplayState) -> None:
        """The pending plan is approved: vehicles append its stops after their current run."""
        pending, state.pending = state.pending, None
        plan = pending.plan
        people = {r.id: r for r in self.store.residents}
        shelters = {s.id: s for s in self.store.shelters}
        for route in plan.routes:
            tr = state.tracks[route.vehicle]
            leave_prev = pending.starts[route.vehicle]
            for stop, eta in zip(route.stops, route.eta_min, strict=True):
                arrive = plan.t + timedelta(minutes=eta)
                if stop in shelters:
                    s = shelters[stop]
                    leg = Leg(stop, "dropoff", (s.lat, s.lon), leave_prev, arrive,
                              arrive + timedelta(minutes=UNLOAD_MIN))
                else:
                    if stop in state.picked_up:
                        continue
                    r = people[stop]
                    leg = Leg(stop, "pickup", (r.lat, r.lon), leave_prev, arrive,
                              arrive + timedelta(minutes=r.load_minutes))
                tr.legs.append(leg)
                leave_prev = leg.depart

    @staticmethod
    def _vehicle_now(tr: Track, t: datetime) -> Vehicle:
        """Where the vehicle is at t, for display."""
        pos, status = tr.pos, "idle"
        if tr.legs:
            leg = tr.legs[0]
            if leg.arrive <= t:
                pos, status = leg.pos, "loading"
            elif leg.leave_prev <= t:
                f = (t - leg.leave_prev) / (leg.arrive - leg.leave_prev)
                pos = (tr.pos[0] + f * (leg.pos[0] - tr.pos[0]),
                       tr.pos[1] + f * (leg.pos[1] - tr.pos[1]))
                status = "en_route"
        free = tr.legs[-1].depart if tr.legs else t
        return tr.vehicle.model_copy(update={
            "lat": round(pos[0], 6), "lon": round(pos[1], 6), "status": status,
            "available_in_min": round(max((free - t).total_seconds() / 60, 0), 1),
        })


def world_state(frame: Frame, t: datetime, dataset: str, decisions: list[Decision]) -> WorldState:
    s = frame.snapshot
    return WorldState(
        t=t,
        dataset=dataset,
        residents=s.residents,
        vehicles=frame.vehicles,
        shelters=s.shelters,
        detections=s.detections,
        reports=s.reports,
        facilities=s.facilities,
        orders=s.orders,
        outlook=frame.outlook,
        risks=frame.risks,
        plan=frame.plan,
        decisions=decisions,
        picked_up=frame.picked_up,
        schedule=frame.schedule,
        plan_takes_effect_at=frame.plan_takes_effect_at,
    )
