"""Loads one dataset folder and serves "the world as it was known at time t".

A dataset folder (see data/README.md for the full contract) looks like:

    meta.json            name, bbox, replay window, synthetic flag
    residents.jsonl      Resident, one JSON object per line
    facilities.jsonl     Facility (real licensed care facilities)
    vehicles.jsonl       Vehicle
    shelters.jsonl       Shelter
    detections.jsonl     FireDetection (satellites)
    fire_reports.jsonl   FireReport (911/radio reports from the published timelines)
    wind.jsonl           WindForecast
    evac_orders.jsonl    EvacOrder

`OUTRUN_DATASET=fixtures` (default) reads data/fixtures/eaton_fake/ (fake, for tests).
`OUTRUN_DATASET=eaton` reads data/processed/eaton/ (real, see data/BUILD.md).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TypeVar

import h3
from pydantic import BaseModel

from backend.clock import ReplayClock, as_of, parse_t
from backend.knowledge import KnowledgeParams, assign_knowledge
from backend.schemas import (
    H3_RES,
    EvacOrder,
    Facility,
    FireDetection,
    FireReport,
    Resident,
    Shelter,
    Vehicle,
    WindForecast,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.environ.get("OUTRUN_DATA_DIR", REPO_ROOT / "data"))
DATASETS = {
    "fixtures": DATA_DIR / "fixtures" / "eaton_fake",
    "eaton": DATA_DIR / "processed" / "eaton",
    # Development set for the forecast: same night, another fire (scripts/fires.py).
    "palisades": DATA_DIR / "processed" / "palisades",
}
# Bounding box for FIRMS/GOES/HRRR downloads and spatial tests (Western Eaton fire area)
EATON_DOWNLOAD_BOX = {"west": -118.23, "south": 34.12, "east": -118.03, "north": 34.26}

# Files a real dataset may borrow from the fake set while it's being built (people and fleet).
FILL_FROM_FAKE = ("residents.jsonl", "facilities.jsonl", "vehicles.jsonl", "shelters.jsonl")

M = TypeVar("M", bound=BaseModel)


def read_jsonl(path: Path, model: type[M], *, optional: bool = False) -> list[M]:
    if optional and not path.exists():
        return []
    with path.open() as f:
        return [model.model_validate_json(line) for line in f if line.strip()]


def write_jsonl(path: Path, records: list[BaseModel]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for r in records:
            f.write(r.model_dump_json(exclude_none=True) + "\n")


@dataclass(frozen=True)
class Snapshot:
    """What existed at time t. This is the only view engines ever get."""

    t: datetime
    residents: list[Resident]
    vehicles: list[Vehicle]
    shelters: list[Shelter]
    detections: list[FireDetection]
    reports: list[FireReport]
    facilities: list[Facility]
    wind: list[WindForecast]
    orders: list[EvacOrder]


class DataStore:
    """`population` is everyone who may need help (the truth the evaluation scores against).
    `residents` is who the planner can know about, with `known_at` set by backend/knowledge.py.
    """

    def __init__(self, folder: Path, knowledge: KnowledgeParams | None = None, seed: int = 0):
        if not (folder / "meta.json").exists():
            raise FileNotFoundError(
                f"No dataset at {folder}. Run `uv run python scripts/make_fake_data.py` for "
                "fixtures, or the pipeline for real data."
            )
        self.folder = folder
        self.meta = json.loads((folder / "meta.json").read_text())
        self.name: str = self.meta["name"]
        self.synthetic: bool = self.meta.get("synthetic", True)
        # While the real dataset is being built (data/BUILD.md), missing files are filled in:
        self.fake_inputs: list[str] = []  # people/fleet files borrowed from the fake set
        self.missing_inputs: list[str] = []  # fire files not built yet, left empty
        self.population = read_jsonl(self._path("residents.jsonl"), Resident)
        self.vehicles = read_jsonl(self._path("vehicles.jsonl"), Vehicle)
        self.shelters = read_jsonl(self._path("shelters.jsonl"), Shelter)
        self.detections = read_jsonl(self._path("detections.jsonl"), FireDetection, optional=True)
        self.orders = read_jsonl(self._path("evac_orders.jsonl"), EvacOrder, optional=True)
        self.reports = read_jsonl(self._path("fire_reports.jsonl"), FireReport, optional=True)
        self.facilities = read_jsonl(self._path("facilities.jsonl"), Facility, optional=True)
        if knowledge is None and self.meta.get("live"):
            # Live: nobody's help call is simulated. The planner knows care homes, the pre-fire
            # list, and real help requests (POST /requests) as they come in.
            knowledge = KnowledgeParams(never_call=1.0)
        known = assign_knowledge(
            self.population, self.orders, self.reports, self.detections, seed, knowledge
        )
        self.residents = known.residents
        self.never_known = known.never_known
        self.wind = read_jsonl(self._path("wind.jsonl"), WindForecast, optional=True)
        self.cells = study_cells(folder, self.meta)

    def _path(self, name: str) -> Path:
        """Where to read `name` from. A fake dataset must be complete. A real one may still be
        missing files: people and fleet come from the fake set (listed in fake_inputs); fire
        files stay empty (listed in missing_inputs), because a fake fire is never mixed with
        the real one."""
        path = self.folder / name
        if path.exists() or self.synthetic:
            return path
        if name in FILL_FROM_FAKE:
            self.fake_inputs.append(name)
            return DATASETS["fixtures"] / name
        self.missing_inputs.append(name)
        return path

    def reload_live_feeds(self) -> None:
        """A live area pulled new feeds into its folder (backend/area.py refresh_fire): read
        the fire detections, wind, alerts, the incident's report and the area notes again.
        People, fleet, shelters and reports added through the API stay as they are."""
        self.meta = json.loads((self.folder / "meta.json").read_text())
        self.detections = read_jsonl(self.folder / "detections.jsonl", FireDetection)
        self.wind = read_jsonl(self.folder / "wind.jsonl", WindForecast)
        self.orders = read_jsonl(self.folder / "evac_orders.jsonl", EvacOrder)
        on_file = read_jsonl(self.folder / "fire_reports.jsonl", FireReport, optional=True)
        added = [r for r in self.reports  # through the API since setup (intake, drills)
                 if r.id not in {f.id for f in on_file} and not r.id.startswith("nifc_")]
        self.reports = on_file + added

    def area_info(self) -> dict:
        """Where the dataset is, and what is approximate there (an area set up on demand
        lists its approximations; a live area lists the fire weather in effect)."""
        return {"bbox": self.meta["bbox"], "live": bool(self.meta.get("live")),
                "approximations": self.meta.get("approximations", []),
                "fire_weather": self.meta.get("fire_weather", []),
                "feeds_pulled_at": self.meta.get("feeds_pulled_at"),
                "incident": self.meta.get("incident"),
                "time_zone": self.meta.get("time_zone", "America/Los_Angeles")}

    @property
    def complete(self) -> bool:
        """Real, with every input built: what judges may see (PRD: no fake data after Oct 11)."""
        return not self.synthetic and not self.fake_inputs and not self.missing_inputs

    @classmethod
    def from_env(cls, seed: int = 0) -> DataStore:
        key = os.environ.get("OUTRUN_DATASET", "fixtures")
        folder = DATASETS.get(key, Path(key))  # a known name, or a path to any dataset folder
        return cls(folder, seed=seed)

    def make_clock(self) -> ReplayClock:
        replay = self.meta["replay"]
        return ReplayClock(
            start=parse_t(replay["start"]),
            end=parse_t(replay["end"]),
            step=timedelta(minutes=replay["step_minutes"]),
        )

    def add_resident(self, resident: Resident) -> None:
        """Help requests become residents. `known_at` keeps them hidden before they arrived."""
        self.residents.append(resident)

    def add_report(self, report: FireReport) -> None:
        """Fire reports from the Intake agent. `reported_at` keeps them hidden before then."""
        self.reports.append(report)

    def at(self, t: datetime) -> Snapshot:
        """The world as known at time t. Nothing observed or issued after t gets through."""
        return Snapshot(
            t=t,
            residents=as_of(self.residents, t),
            vehicles=list(self.vehicles),
            shelters=as_of(self.shelters, t),  # real shelters opened during the night
            detections=as_of(self.detections, t),
            reports=as_of(self.reports, t),
            facilities=list(self.facilities),
            wind=as_of(self.wind, t),
            orders=as_of(self.orders, t),
        )


def study_cells(folder: Path, meta: dict) -> list[str]:
    """The map cells of a dataset: listed in meta["cells"] (e.g. land only, for a coastal
    fire), else every cell covering the bbox."""
    if "cells" in meta:
        return sorted(json.loads((folder / meta["cells"]).read_text()))
    return grid_cells(meta["bbox"])


def grid_cells(bbox: dict) -> list[str]:
    """All H3 cells covering the study area bbox {south, west, north, east}."""
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    poly = h3.LatLngPoly([(s, w), (s, e), (n, e), (n, w)])
    return sorted(h3.h3shape_to_cells(poly, H3_RES))
