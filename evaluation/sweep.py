"""The full evaluation (EVAL_SPEC §6, §7, §10): each tested setting changed one at a time
around the baseline, on 30 synthetic populations, plus the fleet curve, a good and a bad
night, and the baseline extras.

    OUTRUN_DATASET=eaton uv run python -m evaluation.sweep --list        # what runs, what's done
    OUTRUN_DATASET=eaton uv run python -m evaluation.sweep --part 1/3    # this laptop's third
    uv run python -m evaluation.report                                    # the tables

Each run is one full night for one planner, mode, setting and population. It is written as
one line to evaluation/results/ the moment it finishes; runs already there are skipped, so a
crash or a closed lid loses nothing, and the files from several laptops simply sit side by
side (the report reads them all).

A population seed k fixes everything random about the people (EVAL_SPEC §10): where the
estimated residents live (scripts/build_residents.py, seed 20250107 + k; k = 0 is
residents.jsonl itself) and who is on the pre-fire list and when the others call
(backend/knowledge.py, seed k). Every planner and setting uses the same seeds, so every
comparison is paired.

Settings are applied inside the process that runs them. Where the code takes a value as an
argument it gets one (who's known and when, approval delay, speed, the fleet, loading times).
The rest are the engines' own module values, set for the run: the safety margin, the 5th
percentile check, the priority weights. Every run sets every value, so nothing carries over.

The good and bad nights move every condition of the night to its optimistic or pessimistic
end. They keep the fleet (it has its own curve) and the safety margin (a choice, not luck) at
the baseline. Road blockage is not run (it needs the road network rebuilt per run).
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import os
import socket
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import h3

from backend.assumptions import (
    APPROVAL_DELAY_MIN,
    ARRIVAL_PERCENTILE,
    CALL_DELAY_MAX_MIN,
    FRACTION_KNOWN,
    HANDLING_DELAY_MIN,
    NEVER_CALL,
    SAFETY_MARGIN_MIN,
    SPEED_FACTOR,
    TRIGGER_KM,
    VEHICLE_SPECS,
    VULNERABILITY,
)
from backend.knowledge import KnowledgeParams
from backend.replay import Frame, Replay
from backend.schemas import H3_RES, Resident, Vehicle
from backend.store import DATASETS, DataStore
from engines import nowcast, travel_for
from evaluation.arrival_window import ArrivalWindow, perfect_forecast
from evaluation.standin import PLANNERS, after_orders, arrival_windows, outcome

RESULTS = Path(__file__).parent / "results"
POPULATIONS = 30
Z = {10: -1.2816, 5: -1.6449}  # standard normal quantiles: the "plausible arrival" percentile


@dataclass(frozen=True)
class Settings:
    """Everything one run may change. The defaults are the baseline (backend/assumptions.py)."""

    fleet: int | None = None  # None: the real baseline fleet (vehicles.jsonl)
    speed_factor: float = SPEED_FACTOR
    loading: float = 1.0  # x every loading time
    approval_delay_min: float = APPROVAL_DELAY_MIN
    fraction_known: float = FRACTION_KNOWN
    never_call: float = NEVER_CALL
    call_delay_max_min: float = CALL_DELAY_MAX_MIN
    handling_delay_min: float = HANDLING_DELAY_MIN
    trigger_km: float = TRIGGER_KM
    safety_margin_min: float = SAFETY_MARGIN_MIN
    percentile: int = ARRIVAL_PERCENTILE
    equal_weights: bool = False


BASELINE = Settings()

# The tested values (EVAL_SPEC §6), one setting at a time around the baseline.
TESTED: dict[str, list] = {
    "fleet": [2, 5, 10, 20, 40, 80],
    "speed_factor": [0.25, 0.5, 0.75],
    "loading": [0.5, 1.0, 2.0],
    "approval_delay_min": [0, 5, 10, 20],
    "fraction_known": [0, 0.25, 0.5, 1.0],
    "never_call": [0, 0.10, 0.25],
    "call_delay_max_min": [30, 60],
    "handling_delay_min": [5, 15, 30],
    "trigger_km": [1, 2, 3],
    "safety_margin_min": [15, 30, 45],
}

# Every condition of the night at its optimistic and its pessimistic end.
GOOD_NIGHT = Settings(speed_factor=0.75, loading=0.5, approval_delay_min=0, fraction_known=1.0,
                      never_call=0, call_delay_max_min=30, handling_delay_min=5, trigger_km=3)
BAD_NIGHT = Settings(speed_factor=0.25, loading=2.0, approval_delay_min=20, fraction_known=0,
                     never_call=0.25, call_delay_max_min=60, handling_delay_min=30, trigger_km=1)

HEADLINE = ("ours", "dispatcher rule")


@dataclass(frozen=True)
class Run:
    group: str  # sweep | fleet_curve | good_night | bad_night | extras | p5 | equal_weights
    label: str  # "baseline", or the one setting changed, e.g. "speed_factor=0.25"
    settings: Settings
    planner: str
    mode: str
    population: int

    @property
    def key(self) -> str:
        return f"{self.group}|{self.label}|{self.planner}|{self.mode}|{self.population}"


def runs(populations: int = POPULATIONS) -> list[Run]:
    """Every run of the full evaluation, in a fixed order."""
    out: list[Run] = []

    def add(group: str, label: str, s: Settings, planners=HEADLINE, mode="our forecast"):
        for k in range(populations):
            for p in planners:
                out.append(Run(group, label, s, p, mode, k))

    add("sweep", "baseline", BASELINE)
    for name, values in TESTED.items():
        for v in values:
            if getattr(BASELINE, name) != v:
                add("sweep", f"{name}={v:g}", dataclasses.replace(BASELINE, **{name: v}))
    for n in TESTED["fleet"]:  # the curve at 100% known (the 25% curve is in the sweep)
        add("fleet_curve", f"fleet={n}", Settings(fleet=n, fraction_known=1.0))
    add("good_night", "good night", GOOD_NIGHT)
    add("bad_night", "bad night", BAD_NIGHT)
    add("extras", "baseline", BASELINE, mode="wait for orders")
    add("extras", "baseline", BASELINE, planners=("closest first",))
    add("extras", "baseline", BASELINE, planners=("ours",), mode="true fire path")
    add("p5", "percentile=5", Settings(percentile=5))
    add("equal_weights", "equal weights", Settings(equal_weights=True))
    # Population by population, the headline comparisons first: a night cut short still has
    # every setting, on fewer populations.
    first = {("sweep", "baseline"): 0, ("extras", "baseline"): 1}
    return sorted(out, key=lambda r: (r.population, first.get((r.group, r.label), 2)))


# --------------------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------------------


def fleet(n: int, like: list[Vehicle]) -> list[Vehicle]:
    """n vehicles: 40% wheelchair vans, 40% ambulances, the rest buses, at least one van and
    one ambulance (EVAL_SPEC §6), at the real fleet's depot."""
    vans, ambulances = max(1, round(0.4 * n)), max(1, round(0.4 * n))
    counts = {"wheelchair_van": vans, "ambulance": ambulances,
              "bus": max(0, n - vans - ambulances)}
    depot = like[0]
    out = []
    for kind, count in counts.items():
        prefix, seats, wheelchair, stretcher = VEHICLE_SPECS[kind]
        out += [Vehicle(id=f"{prefix}_{i:02d}", type=kind, seats=seats,
                        wheelchair_spaces=wheelchair, stretcher_spaces=stretcher,
                        lat=depot.lat, lon=depot.lon, depot=depot.depot)
                for i in range(1, count + 1)]
    return out


@lru_cache(maxsize=1)
def _people_inputs():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # scripts/ isn't a package
    build_residents = importlib.import_module("scripts.build_residents")
    return build_residents, build_residents.inputs()


def population(folder: Path, k: int) -> list[Resident] | None:
    """Population k. Only the real Eaton set is redrawn; any other dataset keeps its file."""
    if folder.resolve() != DATASETS["eaton"].resolve():
        return None
    build_residents, drawn_from = _people_inputs()
    return build_residents.build(build_residents.SEED + k, drawn_from)


def apply_engine_values(s: Settings) -> None:
    """The settings the engines read as their own module values, set for this run."""
    risk = importlib.import_module("engines.risk")
    routing = importlib.import_module("engines.routing")
    nowcast_module = importlib.import_module("engines.nowcast")
    risk.SAFETY_MARGIN_MIN = routing.SAFETY_MARGIN_MIN = s.safety_margin_min
    nowcast_module.Z_P10 = Z[s.percentile]
    risk.VULNERABILITY = dict.fromkeys(VULNERABILITY, 1.0) if s.equal_weights else VULNERABILITY


@lru_cache(maxsize=2)
def _windows(folder: Path) -> dict[str, ArrivalWindow]:
    return arrival_windows(DataStore(folder))


def store_for(folder: Path, s: Settings, k: int) -> DataStore:
    people = population(folder, k)
    if people is None:
        people = DataStore(folder).population
    if s.loading != 1.0:
        people = [r.model_copy(update={"load_minutes": r.load_minutes * s.loading})
                  for r in people]
    knowledge = KnowledgeParams(
        fraction_known=s.fraction_known, never_call=s.never_call,
        call_delay_max_min=s.call_delay_max_min, handling_delay_min=s.handling_delay_min,
        trigger_km=s.trigger_km)
    store = DataStore(folder, knowledge=knowledge, seed=k, population=people)
    if s.fleet is not None:
        store.vehicles = fleet(s.fleet, store.vehicles)
    return store


def run_one(run: Run, folder: Path) -> dict:
    """One full night, scored. Runs in a worker process."""
    started = time.time()
    s = run.settings
    apply_engine_values(s)
    store = store_for(folder, s, run.population)
    windows = _windows(folder)
    travel = travel_for(folder)
    if hasattr(travel, "speed_factor"):
        travel.speed_factor = s.speed_factor
    planner, forecast = PLANNERS[run.planner], nowcast
    if run.mode == "wait for orders":
        planner = after_orders(planner, store.orders)
    elif run.mode == "true fire path":
        forecast = perfect_forecast(windows)
    frames = Replay(store, planner=planner, travel=travel, forecast=forecast,
                    approval_delay_min=s.approval_delay_min).run()
    scored = outcome(store.population, frames[-1].picked_up, windows)
    return {
        "key": run.key, "group": run.group, "label": run.label, "planner": run.planner,
        "mode": run.mode, "population": run.population, "settings": dataclasses.asdict(s),
        "reached": scored.strict.reached, "strict": scored.strict.saved,
        "lenient": scored.lenient.saved, "in_time": scored.in_time,
        "too_late": scored.too_late, "fire_never_came": scored.fire_never_came,
        **measure(frames, store.population, windows, s.safety_margin_min),
        "seconds": round(time.time() - started, 1),
        "dataset": store.name, "host": socket.gethostname(),
    }


def measure(frames: list[Frame], people: list[Resident], windows: dict[str, ArrivalWindow],
            margin_min: float) -> dict:
    """The other metrics (EVAL_SPEC §7), read off the vehicles at every step (10-minute
    resolution, so driver exposure is approximate: vehicle-minutes in a block the fire was
    first seen in within the safety margin after the vehicle was there, or earlier)."""
    first_dispatch, busy, slots, exposure = None, 0, 0, 0.0
    step_min = 10.0
    if len(frames) > 1:
        step_min = (_t(frames[1]) - _t(frames[0])).total_seconds() / 60
    escalated: set[str] = set()
    for f in frames:
        t = _t(f)
        escalated.update(f.plan.escalated_fire_command or [])
        for v in f.vehicles:
            slots += 1
            if v.status == "idle":
                continue
            busy += 1
            if first_dispatch is None:
                first_dispatch = (t - _t(frames[0])).total_seconds() / 60
            # Exposure: in a block within the margin of the first evidence of fire there.
            # (Not the window's earliest end: for blocks no satellite saw clear that is the
            # fire's start, which would count every trip there. Blocks only DINS timed have
            # no time of their own.)
            w = windows.get(h3.latlng_to_cell(v.lat, v.lon, H3_RES))
            if (w is not None and not w.dins_only
                    and (w.latest - t).total_seconds() / 60 <= margin_min):
                exposure += step_min
    cell_of = {r.id: r.h3 for r in people}
    return {
        "first_dispatch_min": first_dispatch,
        "vehicle_use": round(busy / slots, 4) if slots else 0.0,
        "escalated": len(escalated),
        "escalated_fire_reached": sum(cell_of.get(rid) in windows for rid in escalated),
        "driver_exposure_min": exposure,
    }


def _t(frame: Frame) -> datetime:
    return frame.plan.t


# --------------------------------------------------------------------------------------
# Running many
# --------------------------------------------------------------------------------------


def load(folder: Path = RESULTS) -> list[dict]:
    """Every finished run in the folder (all laptops' files), once each."""
    rows: dict[str, dict] = {}
    for path in sorted(folder.glob("runs*.jsonl")):
        for line in path.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                rows.setdefault(row["key"], row)
    return list(rows.values())


def done_keys(folder: Path = RESULTS) -> set[str]:
    return {row["key"] for row in load(folder)}


def part(all_runs: list[Run], i: int, n: int) -> list[Run]:
    """Laptop i of n: every n-th run, so each part has the same mix of runs."""
    return [r for idx, r in enumerate(all_runs) if idx % n == i - 1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--part", default="1/1", help="this laptop's share, e.g. 2/3")
    parser.add_argument("--workers", type=int, default=None, help="replays at a time")
    parser.add_argument("--populations", type=int, default=POPULATIONS)
    parser.add_argument("--list", action="store_true", help="count the runs; run nothing")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many runs")
    parser.add_argument("--out-dir", type=Path, default=RESULTS, help="where results go")
    args = parser.parse_args()

    folder = DataStore.from_env().folder
    i, n = (int(x) for x in args.part.split("/"))
    mine = part(runs(args.populations), i, n)
    done = done_keys(args.out_dir)
    left = [r for r in mine if r.key not in done]
    todo = left[: args.limit]
    print(f"Dataset {folder.name} · part {i}/{n}: {len(mine)} runs, {len(mine) - len(left)} "
          f"done, {len(left)} to go" + (f" (running {len(todo)} now)" if args.limit else ""))
    if args.list or not todo:
        by_group: dict[str, int] = {}
        for r in mine:
            by_group[r.group] = by_group.get(r.group, 0) + 1
        for g, c in by_group.items():
            print(f"  {g:14} {c:5}")
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out = args.out_dir / f"runs-{socket.gethostname().split('.')[0]}-part{i}of{n}.jsonl"
    # Each replay holds a full dataset (~250 MB), so a laptop runs a few at a time.
    workers = args.workers or max(1, min(4, (os.cpu_count() or 2) - 1))
    started = time.time()
    with ProcessPoolExecutor(workers) as pool, out.open("a") as f:
        futures = {pool.submit(run_one, r, folder): r for r in todo}
        for count, fut in enumerate(as_completed(futures), 1):
            row = fut.result()
            f.write(json.dumps(row) + "\n")
            f.flush()
            share = row["strict"] / row["reached"] if row["reached"] else 0.0
            left = (time.time() - started) / count * (len(todo) - count) / 3600
            print(f"[{count}/{len(todo)}] {row['key']}: {share:.0%} in time "
                  f"({row['seconds']:.0f} s; ~{left:.1f} h left)", flush=True)
    print(f"Done in {(time.time() - started) / 3600:.1f} h -> {out}")


if __name__ == "__main__":
    main()
