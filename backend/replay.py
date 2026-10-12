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
3. Who approves:
   - Auto (evaluation and the exported replay): the plan takes effect `approval_delay_min`
     later. Until then vehicles finish their current run and wait. With a delay longer than
     one step, plans are made less often, which is exactly the cost of slow approval.
   - The manager (the live API: pass `decisions`): the plan waits for a decision on its
     plan_id. Approve and the vehicles take it from that moment; modify applies the manager's
     edits (backend/decisions.py) first; reject drops it. A proposal nobody decides on by the
     next step is replaced by a fresh one, and until a plan is approved vehicles keep the
     schedule they already have: nothing new starts without a person saying yes.

Only data that existed at time t is used (DataStore.at(t)).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.assumptions import APPROVAL_DELAY_MIN, UNLOAD_MIN
from backend.decisions import DecisionError, apply_changes
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
from engines import TravelTime, nowcast, plan_routes, prioritize, travel_for

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
    takes_effect: datetime | None  # None: waiting for the manager
    starts: dict[str, datetime]  # vehicle -> when the plan assumed it is free
    vehicles: dict[str, Vehicle] = field(default_factory=dict)  # as the planner saw them
    outlook: list[FireOutlook] = field(default_factory=list)


@dataclass
class ReplayState:
    t: datetime
    tracks: dict[str, Track]
    picked_up: dict[str, datetime] = field(default_factory=dict)
    pending: _Pending | None = None
    last_plan: Plan | None = None
    last_plan_effect: datetime | None = None
    # auto | awaiting_decision | approved | modified | rejected | expired
    plan_status: str = "auto"


@dataclass(frozen=True)
class Frame:
    """Everything known and decided at time t."""

    snapshot: Snapshot
    outlook: list[FireOutlook]
    risks: list[ResidentRisk]
    plan: Plan
    plan_takes_effect_at: datetime | None
    plan_status: str
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
        decisions: Callable[[], list[Decision]] | None = None,
    ):
        self.store = store
        self.planner = planner
        self.travel = travel or travel_for(store.folder)  # real roads when the dataset has them
        self.delay = timedelta(minutes=approval_delay_min)
        self.decisions = decisions  # None: plans are auto-approved
        self.clock = store.make_clock()
        self.step_times = set(self.clock.times())
        self.invalidate()

    def invalidate(self) -> None:
        """Forget everything computed. Call after the data changes (a new help request)."""
        start = self.clock.start
        tracks = {v.id: Track(v, (v.lat, v.lon)) for v in self.store.vehicles}
        self._states: list[tuple[datetime, ReplayState]] = []
        self._frames: dict[datetime, Frame] = {}
        self._initial = ReplayState(t=start, tracks=tracks)

    def invalidate_from(self, t: datetime) -> None:
        """Forget steps at or after t (a decision made at t changes nothing before it)."""
        self._states = [(when, s) for when, s in self._states if when < t]
        self._frames = {when: f for when, f in self._frames.items() if when < t}

    # -- public ------------------------------------------------------------------------------

    def check_decision(self, d: Decision) -> tuple[int, str] | None:
        """Why the manager's decision can't be applied (HTTP status, message), or None."""
        state = self._state_at(d.t)
        p = state.pending
        if p is None or p.takes_effect is not None:
            if state.last_plan and state.last_plan.plan_id == d.plan_id:
                return 409, f"Plan {d.plan_id} was already {state.plan_status}."
            return 409, "No plan is waiting for a decision right now."
        if p.plan.plan_id != d.plan_id:
            return 409, (f"Plan {d.plan_id} is no longer current: the plan waiting now is "
                         f"{p.plan.plan_id}. Show it to the manager before recording a decision.")
        if d.action == "modify":
            try:
                self._modified(p, d)
            except DecisionError as e:
                return 422, str(e)
        return None

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

    def _state_at(self, t: datetime) -> ReplayState:
        self._compute_until(t)
        before = [s for when, s in self._states if when <= t]
        state = copy.deepcopy(before[-1] if before else self._initial)
        self._step(state, t)
        return state

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
        if self.decisions is None:
            if state.pending is None:
                self._plan(state, snap, outlook, t)
                if state.pending.takes_effect <= t:
                    self._activate(state)
        else:
            if state.pending and t >= state.pending.plan.t + self.clock.step:
                state.pending, state.plan_status = None, "expired"  # nobody decided in time
            if state.pending is None and (t in self.step_times or state.last_plan is None):
                self._plan(state, snap, outlook, t)
                self._decide(state, t)  # a decision made right at t
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
            plan_status=state.plan_status,
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
        if self.decisions is not None:
            self._decide(state, t)
        elif state.pending and state.pending.takes_effect <= t:
            self._move(state, state.pending.takes_effect)
            self._activate(state)
        self._move(state, t)

    def _decide(self, state: ReplayState, t: datetime) -> None:
        """Apply the manager's decision on the waiting plan, if one was made by t."""
        p = state.pending
        if p is None or p.takes_effect is not None:
            return
        end = p.plan.t + self.clock.step
        d = next((d for d in sorted(self.decisions(), key=lambda d: d.t)
                  if d.plan_id == p.plan.plan_id and p.plan.t <= d.t <= t and d.t < end), None)
        if d is None:
            return
        self._move(state, d.t)
        if d.action == "reject":
            state.pending, state.plan_status, state.last_plan_effect = None, "rejected", None
            return
        try:
            plan = p.plan if d.action == "approve" else self._modified(p, d)
        except DecisionError:  # the API refuses these; a stray one changes nothing
            state.pending, state.plan_status = None, "rejected"
            return
        # The new plan replaces what each vehicle would do after its current run.
        for tr in state.tracks.values():
            tr.legs = self._current_run(tr, d.t)
        # Approved later than the plan assumed: each vehicle's route starts that much later.
        shift = {}
        for v_id, tr in state.tracks.items():
            free = tr.legs[-1].depart if tr.legs else d.t
            shift[v_id] = max(free, d.t + self.delay) - p.starts[v_id]
            shift[v_id] = max(shift[v_id], timedelta(0))
        p.plan, p.takes_effect = plan, d.t
        state.last_plan, state.last_plan_effect = plan, d.t
        state.plan_status = "approved" if d.action == "approve" else "modified"
        self._activate(state, shift)

    def _modified(self, p: _Pending, d: Decision) -> Plan:
        known = {r.id: r for r in self.store.at(p.plan.t).residents}
        return apply_changes(p.plan, d.changes, known, p.vehicles, self.store.at(d.t).shelters,
                             p.outlook, self.travel)

    @staticmethod
    def _current_run(tr: Track, t: datetime) -> list[Leg]:
        """The legs of the run a vehicle is on at t: its pickups through the next shelter."""
        kept: list[Leg] = []
        if tr.legs and tr.legs[0].leave_prev <= t:
            for leg in tr.legs:
                kept.append(leg)
                if leg.kind == "dropoff":
                    break
        return kept

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
        # Each vehicle keeps the run it is on; anything after that is re-planned. With a
        # manager deciding, the schedule is only cut back once the new plan is approved.
        runs = {v_id: self._current_run(tr, t) for v_id, tr in state.tracks.items()}
        if self.decisions is None:
            for v_id, tr in state.tracks.items():
                tr.legs = runs[v_id]
        committed = {leg.stop for legs in runs.values() for leg in legs}

        vehicles, starts = [], {}
        for v_id, tr in state.tracks.items():
            run = runs[v_id]
            free_at, pos = (run[-1].depart, run[-1].pos) if run else (t, tr.pos)
            start = max(free_at, t + self.delay)
            starts[v_id] = start
            vehicles.append(tr.vehicle.model_copy(update={
                "lat": pos[0], "lon": pos[1],
                "available_in_min": (start - t).total_seconds() / 60,
                "status": "en_route" if run else "idle",
            }))
        residents = [
            r for r in snap.residents if r.id not in state.picked_up and r.id not in committed
        ]
        risks = prioritize(residents, outlook, t)
        plan = self.planner(risks, residents, vehicles, snap.shelters, outlook, self.travel, t)
        if self.decisions is None:
            state.pending = _Pending(plan, t + self.delay, starts)
            state.last_plan, state.last_plan_effect = plan, t + self.delay
        else:
            state.pending = _Pending(plan, None, starts, {v.id: v for v in vehicles}, outlook)
            state.last_plan, state.last_plan_effect = plan, None
            state.plan_status = "awaiting_decision"

    def _activate(self, state: ReplayState, shift: dict[str, timedelta] | None = None) -> None:
        """The pending plan is approved: vehicles append its stops after their current run."""
        pending, state.pending = state.pending, None
        plan = pending.plan
        people = {r.id: r for r in self.store.residents}
        shelters = {s.id: s for s in self.store.shelters}
        for route in plan.routes:
            tr = state.tracks[route.vehicle]
            late = (shift or {}).get(route.vehicle, timedelta(0))
            leave_prev = pending.starts[route.vehicle] + late
            for stop, eta in zip(route.stops, route.eta_min, strict=True):
                arrive = plan.t + timedelta(minutes=eta) + late
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
        plan_status=frame.plan_status,
    )
