"""The API serves the right data at the right time, and exposes clean tool names."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.store import REPO_ROOT

EXPECTED_TOOLS = {
    "get_fire_outlook", "get_residents_at_risk", "get_current_plan",
    "submit_help_request", "submit_fire_report", "record_decision", "list_decisions",
    "get_world_state",
}


ADDRESSES = {  # a pretend geocoder, so tests never call the Census service
    "2260 N Lake Ave, Altadena, CA": (34.18476, -118.13147),
    "200 N Spring St, Los Angeles, CA": (34.05369, -118.24277),  # outside the study area
}


@pytest.fixture
def client(store):
    return TestClient(create_app(store=store, geocode=ADDRESSES.get))


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_fire_grows_over_time(client):
    early = client.get("/fire/outlook", params={"t": "2025-01-07T20:00:00-08:00"}).json()
    late = client.get("/fire/outlook", params={"t": "2025-01-07T23:00:00-08:00"}).json()
    assert late["cells_burning"] > early["cells_burning"]


def test_state_has_everything(client):
    s = client.get("/state", params={"t": "2025-01-07T21:00:00-08:00"}).json()
    for key in ("residents", "vehicles", "outlook", "risks", "plan", "orders", "reports",
                "facilities"):
        assert key in s
    assert s["plan"]["plan_id"] == "p_20250107T2100"


def test_openapi_tool_names(client):
    spec = client.get("/openapi.json").json()
    ops = {op["operationId"] for path in spec["paths"].values() for op in path.values()}
    assert EXPECTED_TOOLS <= ops


def test_committed_openapi_is_up_to_date():
    """backend/openapi.json must match the code (the dashboard reads it). If this fails:
    make openapi."""
    committed = json.loads((REPO_ROOT / "backend" / "openapi.json").read_text())
    current = create_app().openapi()
    committed.pop("servers"), current.pop("servers")  # depends on where it was generated
    assert committed == current


def test_help_request_respects_time(client):
    body = {"reported_at": "2025-01-07T21:00:00-08:00", "lat": 34.185, "lon": -118.150,
            "needs": "oxygen", "people": 2, "notes": "dad on oxygen, 2nd floor",
            "raw_text": "my dad's on oxygen, 2nd floor, please help"}
    r = client.post("/requests", json=body)
    assert r.status_code == 201
    new = r.json()
    assert new["source"] == "request" and new["vehicle_types"] == ["ambulance", "wheelchair_van"]

    def ids_at(t):
        return {x["id"] for x in client.get("/state", params={"t": t}).json()["residents"]}

    # Visible only after the call-handling delay, which is at least one replay step.
    assert new["known_at"] == "2025-01-07T21:15:00-08:00"
    assert new["id"] not in ids_at("2025-01-07T21:10:00-08:00")
    assert new["id"] in ids_at("2025-01-07T21:15:00-08:00")


def test_fire_report_feeds_the_forecast_from_its_time(client):
    body = {"reported_at": "2025-01-07T18:40:00-08:00", "lat": 34.186, "lon": -118.160,
            "description": "caller sees flames behind the houses on the next street"}
    r = client.post("/reports", json=body)
    assert r.status_code == 201 and r.json()["source"] == "intake"

    def burning(t):
        return client.get("/fire/outlook", params={"t": t}).json()["cells_burning"]

    def reports(t):
        return {x["id"] for x in client.get("/state", params={"t": t}).json()["reports"]}

    assert r.json()["id"] not in reports("2025-01-07T18:39:00-08:00")
    assert r.json()["id"] in reports("2025-01-07T18:40:00-08:00")
    assert burning("2025-01-07T18:40:00-08:00") >= 1


def test_decisions_round_trip(client):
    d = {"plan_id": "p_20250107T2100", "action": "approve", "t": "2025-01-07T21:01:00-08:00"}
    assert client.post("/decisions", json=d).status_code == 201
    assert client.get("/decisions").json()[0]["plan_id"] == "p_20250107T2100"


def test_naive_time_rejected(client):
    assert client.get("/plan", params={"t": "2025-01-07T21:00:00"}).status_code == 422


def test_websocket_sends_state(client):
    with client.websocket_connect("/ws") as ws:
        first = ws.receive_json()
        assert first["t"].startswith("2025-01-07T18:00")
        ws.send_json({"t": "2025-01-07T22:00:00-08:00"})
        assert ws.receive_json()["t"].startswith("2025-01-07T22:00")


def test_ws_and_export_payloads_round_trip(client, tmp_path, monkeypatch):
    """What we send to the dashboard must parse back into WorldState."""
    import sys

    from backend import export
    from backend.schemas import WorldState

    with client.websocket_connect("/ws") as ws:
        WorldState.model_validate_json(ws.receive_text())

    monkeypatch.setattr(sys, "argv", ["outrun-export", "--out", str(tmp_path)])
    export.main()
    first = sorted((tmp_path / "steps").iterdir())[40]
    WorldState.model_validate_json(first.read_text())


def test_help_request_by_address_uses_looked_up_coordinates(client):
    body = {"address": "2260 N Lake Ave, Altadena, CA", "needs": "oxygen",
            "raw_text": "my dad's on oxygen, 2nd floor, 2260 N Lake Ave"}
    r = client.post("/requests", json=body)
    assert r.status_code == 201
    assert (r.json()["lat"], r.json()["lon"]) == ADDRESSES["2260 N Lake Ave, Altadena, CA"]
    # No time given: the call came in at the replay clock's current time (18:00).
    assert r.json()["known_at"] == "2025-01-07T18:15:00-08:00"


def test_unknown_address_tells_the_agent_what_to_ask(client):
    r = client.post("/requests", json={"address": "Mariposa St, Altadena", "needs": "wheelchair"})
    assert r.status_code == 422 and "house number" in r.json()["detail"]


def test_address_outside_the_area_is_refused(client):
    body = {"address": "200 N Spring St, Los Angeles, CA", "needs": "bedbound"}
    r = client.post("/requests", json=body)
    assert r.status_code == 422 and "outside" in r.json()["detail"]


def test_request_needs_a_location(client):
    assert client.post("/requests", json={"needs": "oxygen"}).status_code == 422


def test_fire_report_by_address(client):
    body = {"address": "2260 N Lake Ave, Altadena, CA", "description": "flames behind houses"}
    r = client.post("/reports", json=body)
    assert r.status_code == 201 and r.json()["reported_at"] == "2025-01-07T18:00:00-08:00"
