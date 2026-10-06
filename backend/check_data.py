"""Check a dataset folder against the data contract (data/README.md) before it goes in a PR.

    make check-data                    # the real dataset (data/processed/eaton)
    make check-data DATASET=fixtures   # any name in DATASETS, or a folder path

Reports every problem at once, with file and line, instead of failing on the first. Errors
break the replay or the no-hindsight rule; warnings are worth a look. Exit code 1 on errors.
Missing files are warnings while the real dataset is being built (see DataStore._path).
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import h3
from pydantic import BaseModel, ValidationError

from backend.clock import parse_t
from backend.schemas import (
    H3_RES,
    NEED_PROFILES,
    EvacOrder,
    Facility,
    FireDetection,
    FireReport,
    Resident,
    Shelter,
    Vehicle,
    WindForecast,
)
from backend.store import DATASETS

# File -> (schema, id field or None, must lie inside the study area?)
FILES: dict[str, tuple[type[BaseModel], str | None, bool]] = {
    "residents.jsonl": (Resident, "id", True),
    "facilities.jsonl": (Facility, "id", True),
    "vehicles.jsonl": (Vehicle, "id", False),
    "shelters.jsonl": (Shelter, "id", False),  # shelters can be outside the area
    "fire_reports.jsonl": (FireReport, "id", False),  # fire nearby counts as evidence too
    "detections.jsonl": (FireDetection, "id", False),  # downloads cover a wider box
    "wind.jsonl": (WindForecast, None, False),
    "evac_orders.jsonl": (EvacOrder, None, False),  # a zone in pieces repeats its zone_id
}
HRRR_MAX_LEAD = timedelta(hours=18)


@dataclass
class Finding:
    level: str  # "error" | "warning"
    file: str
    line: int | None
    message: str

    def __str__(self) -> str:
        where = f"{self.file}:{self.line}" if self.line else self.file
        return f"{self.level.upper():7} {where}  {self.message}"


def check_dataset(folder: Path) -> list[Finding]:
    found: list[Finding] = []

    def add(level: str, file: str, line: int | None, message: str) -> None:
        found.append(Finding(level, file, line, message))

    meta_path = folder / "meta.json"
    if not meta_path.exists():
        return [Finding("error", "meta.json", None, f"missing: {folder} is not a dataset")]
    meta = json.loads(meta_path.read_text())
    for key in ("name", "synthetic", "bbox", "h3_res", "replay"):
        if key not in meta:
            add("error", "meta.json", None, f"missing key '{key}'")
    if meta.get("h3_res", H3_RES) != H3_RES:
        add("error", "meta.json", None, f"h3_res must be {H3_RES}")
    box = meta.get("bbox", {})
    real = meta.get("synthetic") is False
    if real:
        try:
            parse_t(meta["fire_start"])
        except (KeyError, ValueError):
            add("error", "meta.json", None, "a real dataset needs fire_start (ignition time with "
                "an offset) and fire_start_source; it bounds every arrival window")
    try:
        start = parse_t(meta["replay"]["start"])
        end = parse_t(meta["replay"]["end"])
    except (KeyError, ValueError) as e:
        add("error", "meta.json", None, f"replay start/end must be times with offsets: {e}")
        start = end = None

    def inside(lat: float, lon: float) -> bool:
        return box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]

    loaded: dict[str, list[tuple[int, BaseModel]]] = {}
    for name, (model, id_field, in_area) in FILES.items():
        path = folder / name
        if not path.exists():
            add("warning" if real else "error", name, None, "not built yet" if real else "missing")
            continue
        rows: list[tuple[int, BaseModel]] = []
        for n, text in enumerate(path.read_text().splitlines(), start=1):
            if not text.strip():
                continue
            try:
                rows.append((n, model.model_validate_json(text)))
            except ValidationError as e:
                first = e.errors()[0]
                field = ".".join(str(x) for x in first["loc"]) or "(record)"
                add("error", name, n, f"{field}: {first['msg']}")
        loaded[name] = rows
        if not path.read_text().strip():
            add("warning", name, None, "empty file")
        if id_field:
            counts = Counter(getattr(r, id_field) for _, r in rows)
            for dup in [k for k, c in counts.items() if c > 1][:5]:
                add("error", name, None, f"duplicate {id_field} '{dup}' ({counts[dup]} times)")
        for n, r in rows:
            lat, lon = getattr(r, "lat", None), getattr(r, "lon", None)
            if in_area and box and lat is not None and not inside(lat, lon):
                add("error", name, n, f"({lat}, {lon}) is outside the study area")
            cell = getattr(r, "h3", None)
            if cell and lat is not None and cell != h3.latlng_to_cell(lat, lon, H3_RES):
                add("error", name, n, f"h3 {cell} doesn't match ({lat}, {lon}) at res {H3_RES}")
            if real and isinstance(r, (FireReport, Facility, EvacOrder)) and not r.source:
                add("error", name, n, "real data needs a source (citation)")
            if real and isinstance(r, Shelter) and not r.source:
                add("warning", name, n, "shelter has no source (citation)")
        _check_times(name, rows, start, end, add)

    _check_residents(loaded, real, add)
    return found


def _check_times(name, rows, start, end, add) -> None:
    for n, r in rows:
        if isinstance(r, FireDetection) and r.available_at and r.available_at < r.observed_at:
            add("error", name, n, "available_at is before observed_at (published before seen)")
        if isinstance(r, WindForecast):
            if r.run_at and r.issued_at and r.issued_at < r.run_at:
                add("error", name, n, "issued_at is before run_at (published before the run)")
            if r.run_at and not (r.run_at <= r.valid_at <= r.run_at + HRRR_MAX_LEAD):
                add("error", name, n, "valid_at must be 0-18 h after run_at")
        if start and isinstance(r, FireReport | EvacOrder):
            when = r.visible_from()
            if when < start - timedelta(hours=12) or when > end + timedelta(hours=12):
                add("warning", name, n, f"time {when.isoformat()} is far outside the replay")


def _check_residents(loaded, real, add) -> None:
    residents = loaded.get("residents.jsonl", [])
    facility_ids = {f.id for _, f in loaded.get("facilities.jsonl", [])}
    for n, r in residents:
        types, minutes = NEED_PROFILES[r.needs]
        if sorted(r.vehicle_types) != sorted(types) or r.load_minutes != minutes:
            add("error", "residents.jsonl", n,
                f"vehicle_types/load_minutes must come from NEED_PROFILES['{r.needs}']")
        if r.facility_id and "facilities.jsonl" in loaded and r.facility_id not in facility_ids:
            add("error", "residents.jsonl", n, f"facility_id '{r.facility_id}' isn't in "
                "facilities.jsonl")
        if real and r.source not in ("facility", "estimated"):
            add("error", "residents.jsonl", n, f"source must be facility or estimated, not "
                f"'{r.source}' (who is known when is applied at load)")
        if r.known_at is not None:
            add("error", "residents.jsonl", n, "known_at is set at load by backend/knowledge.py")


def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else "eaton"
    folder = DATASETS.get(key, Path(key))
    found = check_dataset(folder)
    shown: Counter = Counter()
    repeats = Counter((f.level, f.file, f.message) for f in found)
    for f in found:  # show the first 3 lines of each repeated problem, then a count
        key = (f.level, f.file, f.message)
        shown[key] += 1
        if shown[key] <= 3:
            print(f)
        if shown[key] == 3 and repeats[key] > 3:
            print(f"        ... and {repeats[key] - 3} more like this")
    errors = sum(f.level == "error" for f in found)
    print(f"\n{folder}: {errors} errors, {len(found) - errors} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
