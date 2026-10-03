"""Risk and priority: who is most at risk, and by when must they be picked up.

    deadline = plausible fire arrival (10th percentile) - safety margin
             = the latest time a vehicle may LEAVE the pickup address
    priority = P(fire arrives) x vulnerability weight

The deadline is the driver-safety rule applied at the pickup hex: the router checks the same
rule for every hex a vehicle passes through (engines/routing.py). Constants live in
backend/assumptions.py.

STUB uses p_3h as "P(fire arrives)". The real version should use the probability that fire
arrives before our earliest possible pickup, which needs travel times (see engines/README.md).
"""

from __future__ import annotations

from datetime import datetime

from backend.assumptions import AT_RISK_P3H, SAFETY_MARGIN_MIN, VULNERABILITY
from backend.schemas import FireOutlook, Resident, ResidentRisk


def prioritize(
    residents: list[Resident], outlook: list[FireOutlook], t: datetime
) -> list[ResidentRisk]:
    """One ResidentRisk per resident, most urgent first."""
    by_cell = {o.h3: o for o in outlook}
    risks = []
    for r in residents:
        o = by_cell.get(r.h3)
        p1, p2, p3 = (o.p_1h, o.p_2h, o.p_3h) if o else (0.0, 0.0, 0.0)
        arrival = o.arrival_p10_min if o else None
        deadline = None if arrival is None else arrival - SAFETY_MARGIN_MIN
        risks.append(ResidentRisk(
            resident_id=r.id,
            t=t,
            p_1h=p1, p_2h=p2, p_3h=p3,
            arrival_p10_min=arrival,
            deadline_min=deadline,
            priority=round(p3 * VULNERABILITY[r.needs], 4),
            at_risk=r.needs != "none" and p3 >= AT_RISK_P3H,
        ))
    risks.sort(key=lambda k: (-k.priority, k.deadline_min if k.deadline_min is not None else 1e9))
    return risks
