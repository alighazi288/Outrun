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
}

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
        self.population = read_jsonl(folder / "residents.jsonl", Resident)
        self.vehicles = read_jsonl(folder / "vehicles.jsonl", Vehicle)
        self.shelters = read_jsonl(folder / "shelters.jsonl", Shelter)
        self.detections = read_jsonl(folder / "detections.jsonl", FireDetection)
        self.orders = read_jsonl(folder / "evac_orders.jsonl", EvacOrder)
        self.reports = read_jsonl(folder / "fire_reports.jsonl", FireReport, optional=True)
        self.facilities = read_jsonl(folder / "facilities.jsonl", Facility, optional=True)
        known = assign_knowledge(
            self.population, self.orders, self.reports, self.detections, seed, knowledge
        )
        self.residents = known.residents
        self.never_known = known.never_known
        self.wind = read_jsonl(folder / "wind.jsonl", WindForecast)
        self.cells = grid_cells(self.meta["bbox"])

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
            shelters=list(self.shelters),
            detections=as_of(self.detections, t),
            reports=as_of(self.reports, t),
            facilities=list(self.facilities),
            wind=as_of(self.wind, t),
            orders=as_of(self.orders, t),
        )


def grid_cells(bbox: dict) -> list[str]:
    """All H3 cells covering the study area bbox {south, west, north, east}."""
    s, w, n, e = bbox["south"], bbox["west"], bbox["north"], bbox["east"]
    poly = h3.LatLngPoly([(s, w), (s, e), (n, e), (n, w)])
    return sorted(h3.h3shape_to_cells(poly, H3_RES))
