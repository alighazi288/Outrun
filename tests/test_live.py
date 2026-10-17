"""The live server: areas set up on demand, each with its own Outrun API on the real clock.
Built from a copy of the fake fixtures, no network."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.live import create_live_app
from backend.store import DATASETS, DataStore

NOW = datetime.now(UTC).replace(second=0, microsecond=0)


def make_area(folder: Path, name: str = "demo") -> Path:
    """A fixtures copy dressed as a live area set up a minute ago."""
    out = folder / name
    shutil.copytree(DATASETS["fixtures"], out)
    meta = json.loads((out / "meta.json").read_text())
    start = (NOW - timedelta(hours=2)).replace(minute=NOW.minute // 10 * 10)
    meta.update({
        "name": name, "live": True, "description": f"Live area {name}", "center": [34.19, -118.13],
        "set_up_at": NOW.isoformat(), "feeds_pulled_at": NOW.isoformat(),
        "replay": {"start": start.isoformat(), "end": (start + timedelta(hours=12)).isoformat(),
                   "step_minutes": 10},
        "approximations": ["Fleet: an EXAMPLE fleet"], "fire_weather": ["Red Flag Warning: test"],
    })
    (out / "meta.json").write_text(json.dumps(meta))
    return out


@pytest.fixture
def live(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    make_area(root)
    fire = {"id": "F1", "name": "TEST", "place": "Altadena, CA", "lat": 34.19, "lon": -118.13,
            "status": "active", "discovered_at": NOW.isoformat()}

    def setup(lat, lon, name, fire=None):
        return make_area(root, name.lower().replace(" ", "-").replace(",", ""))

    return TestClient(create_live_app(root=root, fires=lambda days: [fire], setup=setup))


def test_areas_set_up_before_are_served_again(live):
    assert [a["name"] for a in live.get("/areas").json()] == ["demo"]
    health = live.get("/areas/demo/health").json()
    assert health["live"] is True and health["fire_weather"] == ["Red Flag Warning: test"]
    assert health["approximations"] == ["Fleet: an EXAMPLE fleet"]


def test_a_live_area_runs_on_the_real_clock(live):
    clock = live.get("/areas/demo/clock").json()
    now = datetime.fromisoformat(clock["now"])
    assert timedelta(0) <= NOW + timedelta(minutes=1) - now <= timedelta(minutes=11)


def test_setting_up_a_real_fire_mounts_its_area(live):
    r = live.post("/areas", json={"fire_id": "F1"})
    assert r.status_code == 201 and r.json()["url"] == "/areas/test-altadena-ca"
    assert live.get("/areas/test-altadena-ca/health").json()["live"] is True
    assert live.post("/areas", json={"fire_id": "nope"}).status_code == 404


def test_a_setup_that_fails_says_try_again_and_leaves_nothing_behind(tmp_path):
    root = tmp_path / "live"

    def setup(lat, lon, name, fire=None):
        (root / "busy-town").mkdir(parents=True)
        (root / "busy-town" / "meta.json").write_text("{}")
        raise OSError("HTTP Error 429: Too Many Requests")

    client = TestClient(create_live_app(root=root, fires=lambda days: [], setup=setup))
    r = client.post("/areas", json={"lat": 34.2, "lon": -118.1, "name": "Busy Town"})
    assert r.status_code == 503 and "try again" in r.json()["detail"]
    assert not (root / "busy-town").exists()
    assert client.get("/areas").json() == []


def test_a_half_built_area_is_not_served(tmp_path):
    root = tmp_path / "live"
    root.mkdir()
    meta = json.loads((make_area(root, "half").joinpath("meta.json")).read_text())
    del meta["feeds_pulled_at"]
    (root / "half" / "meta.json").write_text(json.dumps(meta))
    assert TestClient(create_live_app(root=root)).get("/areas").json() == []


def test_a_drill_is_always_labeled(live):
    r = live.post("/areas/demo/drill", json={"lat": 34.2, "lon": -118.1})
    assert r.status_code == 201
    report = r.json()
    assert report["id"] == "drill_1" and report["description"].startswith("DRILL")
    assert "not a real one" in report["source"]


def test_feeds_are_pulled_again_once_they_are_10_minutes_old(tmp_path):
    folder = make_area(tmp_path)
    calls, clock = [], [NOW + timedelta(minutes=1)]
    app = create_app(store=DataStore(folder), refresh=lambda f, t: calls.append(t),
                     now=lambda: clock[0])
    client = TestClient(app)
    client.get("/health")
    assert calls == [], "fresh feeds are not pulled again"
    clock[0] = NOW + timedelta(minutes=11)
    client.get("/health")
    client.get("/health")
    assert calls == [clock[0]], "pulled once, then fresh again"


def test_a_failed_refresh_keeps_the_area_up_and_tries_again_in_2_minutes(tmp_path):
    folder = make_area(tmp_path)
    calls, clock = [], [NOW + timedelta(minutes=11)]

    def refresh(f, t):
        calls.append(t)
        raise OSError("HTTP Error 429: Too Many Requests")

    client = TestClient(create_app(store=DataStore(folder), refresh=refresh,
                                   now=lambda: clock[0]))
    assert client.get("/health").status_code == 200
    assert client.get("/state").status_code == 200, "the last good data is still served"
    assert len(calls) == 1
    clock[0] += timedelta(minutes=2)
    client.get("/health")
    assert len(calls) == 2


def test_a_live_area_never_simulates_help_calls(tmp_path):
    store = DataStore(make_area(tmp_path))
    estimated = [r for r in store.population if r.source == "estimated"]
    known = {r.id for r in store.residents}
    assert all(r.known_at is None for r in store.residents if r.source == "estimated")
    assert len(known & {r.id for r in estimated}) < len(estimated), "only the pre-fire list"
