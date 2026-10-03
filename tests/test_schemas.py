"""The shared formats accept the brief's examples and reject bad data."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from backend.schemas import Decision, FireOutlook, Plan, Resident, Vehicle, capacity_demand


def test_fixtures_load(store):
    assert len(store.population) == 70  # 50 estimated + 20 in two fake care facilities
    assert len(store.vehicles) == 5
    assert store.detections and store.reports and store.facilities
    assert store.wind and store.orders and store.shelters
    assert store.meta["synthetic"] is True


def test_brief_examples_validate():
    Resident.model_validate({
        "id": "r_0412", "lat": 34.1897, "lon": -118.1532, "h3": "8929a1d...",
        "needs": "wheelchair", "vehicle_types": ["wheelchair_van", "ambulance"],
        "load_minutes": 12, "people": 1, "source": "registry",
    })
    Vehicle.model_validate({
        "id": "v_03", "type": "wheelchair_van", "seats": 6, "wheelchair_spaces": 2,
        "lat": 34.17, "lon": -118.13, "status": "idle",
    })
    FireOutlook.model_validate({
        "t": "2025-01-07T23:40:00-08:00", "h3": "8929a1d...",
        "p_1h": 0.18, "p_2h": 0.47, "p_3h": 0.71, "arrival_p10_min": 95,
    })
    Plan.model_validate({
        "t": "2025-01-07T23:40:00-08:00", "plan_id": "p_0021",
        "routes": [{"vehicle": "v_03", "stops": ["r_0412", "r_0388", "shelter_2"],
                    "eta_min": [9, 17, 31]}],
        "unreachable": ["r_0901"],
        "reasons": {"r_0412": "71% chance fire arrives within 90 min; wheelchair user"},
    })
    Decision.model_validate({
        "plan_id": "p_0021", "action": "approve", "by": "emergency_manager",
        "t": "2025-01-07T23:41:00-08:00", "changes": [],
    })


def test_naive_times_rejected():
    with pytest.raises(ValidationError):
        FireOutlook(t=datetime(2025, 1, 7, 23, 40), h3="x", p_1h=0.1, p_2h=0.2, p_3h=0.3,
                    arrival_p10_min=None)


def test_probabilities_must_be_monotone():
    with pytest.raises(ValidationError):
        FireOutlook(t="2025-01-07T23:40:00-08:00", h3="x", p_1h=0.5, p_2h=0.4, p_3h=0.6,
                    arrival_p10_min=None)


def test_unknown_fields_rejected():
    with pytest.raises(ValidationError):
        Vehicle(id="v", type="bus", seats=1, lat=0, lon=0, colour="yellow")


def test_capacity_demand(store):
    r = store.residents[0].model_copy(update={"needs": "wheelchair", "people": 2})
    assert capacity_demand(r) == (1, 1, 0)
    r = r.model_copy(update={"needs": "bedbound", "people": 1})
    assert capacity_demand(r) == (0, 0, 1)
