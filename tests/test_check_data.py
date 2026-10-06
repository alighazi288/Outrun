"""The data checker: the fake set and the real folder pass, and real mistakes get caught."""

from __future__ import annotations

import json
import shutil

from backend.check_data import check_dataset
from backend.store import DATASETS


def _errors(folder):
    return [f for f in check_dataset(folder) if f.level == "error"]


def test_fake_dataset_passes():
    assert _errors(DATASETS["fixtures"]) == []


def test_real_dataset_has_no_errors():
    """Missing real files are warnings until Oct 11; a broken real file fails CI."""
    assert _errors(DATASETS["eaton"]) == []


def test_catches_common_mistakes(tmp_path):
    folder = tmp_path / "ds"
    shutil.copytree(DATASETS["fixtures"], folder)
    rows = [json.loads(line) for line in (folder / "residents.jsonl").read_text().splitlines()]
    planted = [
        rows[0],  # the same id twice
        {**rows[1], "id": "r_outside", "lat": 35.0},  # outside the area (and h3 now wrong)
        {**rows[2], "id": "r_profile", "load_minutes": 99},  # not from NEED_PROFILES
        {**rows[3], "id": "r_dangling", "facility_id": "fac_nope"},  # no such facility
    ]
    detection = {"id": "d_x", "lat": 34.19, "lon": -118.13, "h3": "8929a1c052fffff",
                 "observed_at": "2025-01-08T01:02:00-08:00"}
    planted_detections = [
        {**detection, "id": "d_early", "available_at": "2025-01-08T00:50:00-08:00"},
        {**detection, "id": "d_letter", "confidence": "n"},  # FIRMS letter, not mapped
    ]
    with (folder / "residents.jsonl").open("a") as f:
        f.writelines(json.dumps(r) + "\n" for r in planted)
    with (folder / "detections.jsonl").open("a") as f:
        f.writelines(json.dumps(d) + "\n" for d in planted_detections)

    messages = " | ".join(f.message for f in _errors(folder))
    for expected in ("duplicate id", "outside the study area", "doesn't match",
                     "NEED_PROFILES", "isn't in facilities.jsonl", "published before seen",
                     "'low', 'nominal' or 'high'"):
        assert expected in messages, expected


def test_real_dataset_needs_fire_start(tmp_path):
    folder = tmp_path / "real"
    folder.mkdir()
    meta = json.loads((DATASETS["eaton"] / "meta.json").read_text())
    meta.pop("fire_start")
    (folder / "meta.json").write_text(json.dumps(meta))
    assert any("fire_start" in f.message for f in _errors(folder))
