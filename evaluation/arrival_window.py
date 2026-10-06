"""Ground truth: when the fire reached each hex, as a window. EVAL_SPEC section 3.

Per hex, not per building. Building-level timing is not knowable.

A hex is REACHED if any of these holds:
- DINS lists a damaged structure in it. DINS says which buildings burned, never when.
- A VIIRS detection (375 m pixel) lands within 375 m of the hex centre. GOES pixels are
  about 2 km and are not truth.
- A published fire report locates fire in it, and the report is precise enough to name one
  hex (`location_precision_m` at most REPORT_PRECISION_MAX_M).

The arrival WINDOW is:
- latest   = the first evidence of fire in the hex (detection observed, or report time).
             A hex that only DINS reached has no time of its own, so latest = the end of
             the night and the row is flagged `dins_only`.
- earliest = the last moment the hex was seen clear: the fire's start, or a later VIIRS
             pass over the area that found nothing within 375 m of the centre. A pass
             covers the whole study area, so a hex with no detection in that pass was clear.

Scoring (EVAL_SPEC section 7): a pickup counts only if the vehicle LEFT before `earliest`.
That is the strict headline. Lenient scoring against `latest` is reported beside it.

This module uses the whole night (hindsight). It is for scoring only, never for planning.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import h3
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from backend.knowledge import _inside
from backend.schemas import H3_RES, EvacOrder, FireDetection, FireReport, Resident
from engines.travel import haversine_m

DETECTION_RADIUS_M = 375.0  # a VIIRS pixel
# A res-9 hex is about 350 m across. An "area" report (about 1 km) cannot name one hex.
REPORT_PRECISION_MAX_M = 500.0
DINS_DAMAGE_FIELD = "DAMAGE"  # CAL FIRE DINS column
DINS_NO_DAMAGE = {"no damage", "inaccessible", ""}


class ArrivalWindow(BaseModel):
    """When the fire plausibly reached one hex. Written to `arrival_window.jsonl`."""

    model_config = ConfigDict(extra="forbid")

    h3: str
    earliest: AwareDatetime = Field(description="Last time the hex was seen clear")
    latest: AwareDatetime = Field(description="First evidence of fire in the hex")
    reached_by: list[str] = Field(description="Any of: dins, detection, report")
    dins_only: bool = Field(False, description="No timed evidence; latest is the end of the night")
    clear_from: str = Field(description="fire_start or satellite_pass")


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


def dins_hexes(geojson: dict) -> set[str]:
    """Hexes with at least one damaged structure in CAL FIRE's DINS GeoJSON."""
    out: set[str] = set()
    for feature in geojson.get("features", []):
        damage = str((feature.get("properties") or {}).get(DINS_DAMAGE_FIELD, "")).strip()
        if damage.lower() in DINS_NO_DAMAGE:
            continue
        point = _representative_point(feature.get("geometry") or {})
        if point is not None:
            out.add(h3.latlng_to_cell(point[0], point[1], H3_RES))
    return out


def _representative_point(geometry: dict) -> tuple[float, float] | None:
    """(lat, lon) for a Point, or the mean of the outer ring for a Polygon."""
    kind, coords = geometry.get("type"), geometry.get("coordinates")
    if not coords:
        return None
    if kind == "Point":
        return coords[1], coords[0]
    ring = coords[0] if kind == "Polygon" else coords[0][0] if kind == "MultiPolygon" else None
    if not ring:
        return None
    return (sum(c[1] for c in ring) / len(ring), sum(c[0] for c in ring) / len(ring))


def _is_viirs(d: FireDetection) -> bool:
    """Truth needs a 375 m pixel from a VIIRS-class instrument. GOES is never truth, even if a
    record left `pixel_m` at the schema default."""
    return d.pixel_m <= DETECTION_RADIUS_M and not d.source.upper().startswith("GOES")


def fire_start_of(meta: dict) -> datetime:
    """When the fire began, from the dataset's `fire_start`. A real dataset must state it: the
    replay start is a clock setting, not the ignition time. A fake dataset may use its replay
    start, because its fake fire begins with the replay."""
    from backend.clock import parse_t

    if "fire_start" in meta:
        return parse_t(meta["fire_start"])
    if meta.get("synthetic", True):
        return parse_t(meta["replay"]["start"])
    raise ValueError(
        f"Dataset '{meta.get('name')}' is real and has no fire_start in meta.json. Add the "
        "ignition time with its source; the replay start is not a lower bound for arrival."
    )


# --------------------------------------------------------------------------------------
# The window
# --------------------------------------------------------------------------------------


def build_windows(
    cells: list[str],
    detections: list[FireDetection],
    reports: list[FireReport],
    dins: set[str],
    fire_start: datetime,
    night_end: datetime,
) -> dict[str, ArrivalWindow]:
    """One window per reached hex among `cells`."""
    cells_set = set(cells)
    viirs = [d for d in detections if _is_viirs(d)]
    passes = sorted({d.observed_at for d in viirs})
    centre = {c: h3.cell_to_latlng(c) for c in cells}

    # Which passes detected fire within 375 m of each hex centre.
    hit_at: dict[str, set[datetime]] = {c: set() for c in cells}
    for d in viirs:
        for c in h3.grid_disk(d.h3, 2):
            if c in cells_set and haversine_m(centre[c], (d.lat, d.lon)) <= DETECTION_RADIUS_M:
                hit_at[c].add(d.observed_at)

    # Every source that reached a hex is kept, whichever came first.
    first_evidence: dict[str, datetime] = {}
    sources: dict[str, set[str]] = {}

    def seen(cell: str, when: datetime, how: str) -> None:
        sources.setdefault(cell, set()).add(how)
        if cell not in first_evidence or when < first_evidence[cell]:
            first_evidence[cell] = when

    for c, times in hit_at.items():
        for when in times:
            seen(c, when, "detection")
    for r in reports:
        if r.h3 in cells_set and r.location_precision_m <= REPORT_PRECISION_MAX_M:
            seen(r.h3, r.reported_at, "report")

    windows: dict[str, ArrivalWindow] = {}
    for c in sorted(set(first_evidence) | (dins & cells_set)):
        reached_by = {"dins"} if c in dins else set()
        reached_by |= sources.get(c, set())
        if c in first_evidence:
            latest, dins_only = first_evidence[c], False
        else:
            latest, dins_only = night_end, True
        latest = max(latest, fire_start)
        clear_passes = [p for p in passes if fire_start < p < latest and p not in hit_at[c]]
        earliest = max(clear_passes) if clear_passes else fire_start
        windows[c] = ArrivalWindow(
            h3=c, earliest=earliest, latest=latest, reached_by=sorted(reached_by),
            dins_only=dins_only, clear_from="satellite_pass" if clear_passes else "fire_start",
        )
    return windows


# --------------------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------------------


@dataclass
class Score:
    reached: int  # vulnerable residents whose hex the fire reached
    saved: int  # of those, picked up before the fire got there


def score(
    population: list[Resident],
    picked_up: dict[str, datetime],
    windows: dict[str, ArrivalWindow],
    strict: bool = True,
) -> Score:
    """One count per resident record; `none` needs excluded. Strict = before `earliest`."""
    reached = [r for r in population if r.needs != "none" and r.h3 in windows]
    saved = 0
    for r in reached:
        when = picked_up.get(r.id)
        if when is None:
            continue
        w = windows[r.h3]
        if when < (w.earliest if strict else w.latest):
            saved += 1
    return Score(reached=len(reached), saved=saved)


# --------------------------------------------------------------------------------------
# Warning lead time (claim B) against the official order timeline
# --------------------------------------------------------------------------------------


def warned_at(cell: str, orders: list[EvacOrder], kind: str = "order") -> datetime | None:
    """When the first order (or warning) covering this hex's centre was issued."""
    lat, lon = h3.cell_to_latlng(cell)
    times = [
        o.issued_at for o in orders
        if o.kind == kind and o.polygon and _inside(lon, lat, o.polygon)
    ]
    return min(times, default=None)


def warning_lead_min(
    windows: dict[str, ArrivalWindow], orders: list[EvacOrder], kind: str = "order",
) -> dict[str, float | None]:
    """Per reached hex: minutes from the order to the earliest plausible arrival.
    Positive = warned before the fire could have arrived. None = never ordered."""
    out: dict[str, float | None] = {}
    for c, w in windows.items():
        issued = warned_at(c, orders, kind)
        out[c] = None if issued is None else (w.earliest - issued).total_seconds() / 60
    return out


def warning_precision(
    cells: list[str], windows: dict[str, ArrivalWindow], orders: list[EvacOrder],
    kind: str = "order",
) -> float | None:
    """Share of warned hexes the fire reached. Stops "warn everyone at 18:20" from winning."""
    warned = [c for c in cells if warned_at(c, orders, kind) is not None]
    if not warned:
        return None
    return sum(c in windows for c in warned) / len(warned)


# --------------------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------------------


def write_windows(path: Path, windows: dict[str, ArrivalWindow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for w in windows.values():
            f.write(w.model_dump_json() + "\n")


def read_windows(path: Path) -> dict[str, ArrivalWindow]:
    with path.open() as f:
        rows = [ArrivalWindow.model_validate_json(line) for line in f if line.strip()]
    return {w.h3: w for w in rows}


def load_dins(path: Path) -> set[str]:
    return dins_hexes(json.loads(path.read_text())) if path.exists() else set()


def summary(windows: dict[str, ArrivalWindow]) -> dict:
    timed = [w for w in windows.values() if not w.dins_only]
    widths = [(w.latest - w.earliest).total_seconds() / 60 for w in timed]
    return {
        "reached_hexes": len(windows),
        "dins_only_hexes": sum(w.dins_only for w in windows.values()),
        "median_window_min": statistics.median(widths) if widths else None,
        "earliest_from_satellite_pass": sum(w.clear_from == "satellite_pass" for w in timed),
    }
