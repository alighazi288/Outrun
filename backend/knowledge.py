"""Who the planner knows about, and from when.

The population file holds everyone who may need help. It is the truth the evaluation scores
against. This module decides which of them the planner can see, and from what time:

- facility   residents of real licensed care facilities: known from the start.
- registry   FRACTION_KNOWN of the estimated residents are on a list before the fire:
             known from the start.
- call       every other estimated resident becomes known only through a help call:
                 trigger  = the earlier of (a) a real warning/order covering their home is
                            issued, or (b) the first published fire report within TRIGGER_KM.
                            A satellite detection does not start a call. Detections stay in
                            the nowcast.
                 call     = trigger + uniform(0, CALL_DELAY_MAX_MIN)
                 known_at = call + HANDLING_DELAY_MIN
             NEVER_CALL of them never call, and stay unknown to every planner.

The rule uses only records that existed at the trigger time. It never uses the true fire
arrival (that would decide who was knowable from where the fire actually went) and never
our own forecast (a better forecast must not make people knowable sooner).

Every resident gets the same three random draws in the same order for a given seed, so
changing one setting doesn't reshuffle anyone else (results stay paired across settings).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.assumptions import (
    CALL_DELAY_MAX_MIN,
    FRACTION_KNOWN,
    HANDLING_DELAY_MIN,
    NEVER_CALL,
    TRIGGER_KM,
)
from backend.schemas import EvacOrder, FireDetection, FireReport, Resident
from engines.travel import haversine_m


@dataclass(frozen=True)
class KnowledgeParams:
    fraction_known: float = FRACTION_KNOWN
    never_call: float = NEVER_CALL
    call_delay_max_min: float = CALL_DELAY_MAX_MIN
    handling_delay_min: float = HANDLING_DELAY_MIN
    trigger_km: float = TRIGGER_KM


@dataclass
class Knowledge:
    residents: list[Resident]  # everyone the planner ever learns about, with known_at set
    never_known: list[str] = field(default_factory=list)
    triggers: dict[str, datetime] = field(default_factory=dict)  # for audits and tests


def assign_knowledge(
    population: list[Resident],
    orders: list[EvacOrder],
    reports: list[FireReport],
    detections: list[FireDetection],
    seed: int,
    params: KnowledgeParams | None = None,
) -> Knowledge:
    p = params or KnowledgeParams()
    rng = random.Random(seed)
    # Detections stay in the nowcast. Ali, Oct 2: a satellite pass does not start a help call.
    del detections
    evidence = [(r.lat, r.lon, r.visible_from()) for r in reports]
    out = Knowledge(residents=[])

    for r in sorted(population, key=lambda r: r.id):
        on_list, never, delay = rng.random(), rng.random(), rng.random()
        if r.source != "estimated":  # facility residents, live requests: unchanged
            out.residents.append(r)
            continue
        if on_list < p.fraction_known:
            out.residents.append(r.model_copy(update={"source": "registry", "known_at": None}))
            continue
        trigger = first_trigger(r, orders, evidence, p.trigger_km)
        if trigger is None or never < p.never_call:
            out.never_known.append(r.id)
            continue
        out.triggers[r.id] = trigger
        known_at = trigger + timedelta(
            minutes=delay * p.call_delay_max_min + p.handling_delay_min
        )
        out.residents.append(r.model_copy(update={"source": "call", "known_at": known_at}))
    return out


def first_trigger(
    r: Resident,
    orders: list[EvacOrder],
    evidence: list[tuple[float, float, datetime]],
    trigger_km: float,
) -> datetime | None:
    """Earliest time something public could have prompted this resident to call."""
    times = [o.issued_at for o in orders if o.polygon and _inside(r.lon, r.lat, o.polygon)]
    times += [
        seen for lat, lon, seen in evidence
        if haversine_m((r.lat, r.lon), (lat, lon)) <= trigger_km * 1000
    ]
    return min(times, default=None)


def _inside(x: float, y: float, polygon: list[list[float]]) -> bool:
    """Ray-casting point-in-polygon on [lon, lat] pairs."""
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            inside = not inside
    return inside
