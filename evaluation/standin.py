"""STAND-IN evaluation: does our planner get more people out before the fire than the
dispatcher rule, and than waiting for the official orders?

    OUTRUN_DATASET=eaton uv run python -m evaluation.standin --seeds 2   # or: make eval

Headline metric (EVAL_SPEC §7): of the vulnerable residents whose hex the fire reached, the
share picked up before the fire's EARLIEST plausible arrival (strict). The lenient count,
against the LATEST plausible arrival (first evidence of fire), is printed beside it. All
planners get identical everything (same data, same people known at the same times, same
safety rule); only the planner differs.

Each planner runs in three modes:
- our forecast: the product as built.
- wait for orders: the same planner and fleet, but a vehicle only goes to someone once a real
  evacuation order covers their home, as on the night. The orders were public at the time,
  so this uses no hindsight. The gap to "our forecast" is what Outrun's early warning adds.
- true fire path (EVAL_SPEC §6): a perfect forecast, the upper bound. Hindsight. The gap to
  "our forecast" is what the forecast costs.

It also prints the ceiling (people the strict rule can never count: no satellite saw their
block clear after the fire began) and where each planner's pickups went: in time, too late,
or homes the fire never reached.

The arrival window comes from `evaluation/arrival_window.py`: DINS for which hexes burned,
VIIRS passes for when they were last seen clear and first seen burning, published reports
for the hours before the first satellite pass.

What makes this a stand-in:
- A few random draws (seeds) of who is known and when (who's on the registry, when each
  person calls), on one fixed population. The real version: 30 synthetic populations per
  setting, plus the settings sweep and the fleet curve.
- On fake data the numbers mean nothing. They only show the pipeline works.
"""

from __future__ import annotations

import argparse
import os
import statistics
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime

from backend.clock import parse_t
from backend.replay import Replay
from backend.schemas import EvacOrder, Resident
from backend.store import DataStore
from engines import nowcast
from engines.routing import plan_routes, plan_routes_closest, plan_routes_dispatcher
from evaluation.arrival_window import (
    ArrivalWindow,
    Score,
    build_windows,
    fire_start_of,
    load_dins,
    perfect_forecast,
    warned_at,
)
from evaluation.arrival_window import score as score_window

PLANNERS = {
    "ours": plan_routes,
    "dispatcher rule": plan_routes_dispatcher,
    "closest first": plan_routes_closest,
}
MODES = ("our forecast", "wait for orders", "true fire path")


def arrival_windows(store: DataStore) -> dict[str, ArrivalWindow]:
    """The whole night (hindsight), so it's for scoring only, never for planning."""
    return build_windows(
        store.cells, store.detections, store.reports, load_dins(store.folder / "dins.geojson"),
        fire_start_of(store.meta), parse_t(store.meta["replay"]["end"]),
    )


def fire_arrival(store: DataStore, hexes: set[str]) -> dict[str, datetime]:
    """Hex -> latest plausible arrival (first evidence of fire). Kept for the lenient score."""
    return {c: w.latest for c, w in arrival_windows(store).items() if c in hexes}


def score(population: list[Resident], picked_up: dict[str, datetime],
          arrival: dict[str, datetime]) -> Score:
    """Lenient score against a single arrival time per hex."""
    reached = [r for r in population if r.needs != "none" and r.h3 in arrival]
    saved = [r for r in reached if r.id in picked_up and picked_up[r.id] < arrival[r.h3]]
    return Score(reached=len(reached), saved=len(saved))


def after_orders(planner, orders: list[EvacOrder]):
    """The night as it happened: the planner may only send a vehicle to someone once a real
    evacuation order covers their home. Everything else (forecast, safety rule) is unchanged."""
    first_order: dict[str, datetime | None] = {}

    def gated(risks, residents, vehicles, shelters, outlook, travel, t, previous_plan=None):
        ordered = set()
        for r in residents:
            if r.h3 not in first_order:
                first_order[r.h3] = warned_at(r.h3, orders)
            when = first_order[r.h3]
            if when is not None and when <= t:
                ordered.add(r.id)
        risks = [
            k if k.resident_id in ordered else k.model_copy(update={"at_risk": False})
            for k in risks
        ]
        return planner(risks, residents, vehicles, shelters, outlook, travel, t, previous_plan)

    return gated


@dataclass
class Outcome:
    """One replay, scored. The last three count vulnerable people only and add up to
    everyone picked up."""

    strict: Score
    lenient: Score
    in_time: int  # the fire reached their home; picked up before its earliest arrival
    too_late: int  # the fire reached their home; picked up after its earliest arrival
    fire_never_came: int  # picked up from a home the fire never reached


def outcome(population: list[Resident], picked_up: dict[str, datetime],
            windows: dict[str, ArrivalWindow]) -> Outcome:
    strict = score_window(population, picked_up, windows, strict=True)
    taken = [r for r in population if r.needs != "none" and r.id in picked_up]
    reached = sum(r.h3 in windows for r in taken)
    return Outcome(
        strict=strict,
        lenient=score_window(population, picked_up, windows, strict=False),
        in_time=strict.saved,
        too_late=reached - strict.saved,
        fire_never_came=len(taken) - reached,
    )


def cannot_count(population: list[Resident], windows: dict[str, ArrivalWindow]) -> int:
    """Vulnerable people the fire reached whose block no satellite saw clear after the fire
    began: their earliest arrival is the fire's start, so no pickup can beat it (strict)."""
    return sum(
        r.needs != "none" and r.h3 in windows and windows[r.h3].clear_from == "fire_start"
        for r in population
    )


def replay_once(seed: int, planner_name: str, mode: str) -> Outcome:
    """One full-night replay of one planner in one mode, scored."""
    store = DataStore.from_env(seed=seed)
    windows = arrival_windows(store)
    planner, forecast = PLANNERS[planner_name], nowcast
    if mode == "wait for orders":
        planner = after_orders(planner, store.orders)
    elif mode == "true fire path":
        forecast = perfect_forecast(windows)
    final = Replay(store, planner=planner, forecast=forecast).run()[-1]
    return outcome(store.population, final.picked_up, windows)


def run(seeds: list[int], workers: int | None = None) -> dict[tuple[str, str], list[Outcome]]:
    """(planner, mode) -> one Outcome per seed, in seed order. Replays run in parallel."""
    jobs = [(s, name, mode) for s in seeds for name in PLANNERS for mode in MODES]
    # Each replay holds a full dataset (~250 MB), so a laptop runs a few at a time.
    workers = workers or max(1, min(len(jobs), (os.cpu_count() or 2) - 1, 4))
    with ProcessPoolExecutor(workers) as pool:
        outcomes = list(pool.map(replay_once, *zip(*jobs, strict=True)))
    results: dict[tuple[str, str], list[Outcome]] = {}
    for (_, name, mode), o in zip(jobs, outcomes, strict=True):
        results.setdefault((name, mode), []).append(o)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5, help="draws of who is known and when")
    args = parser.parse_args()
    seeds = list(range(args.seeds))

    store = DataStore.from_env()
    windows = arrival_windows(store)
    results = run(seeds)
    median = statistics.median

    def med(key: tuple[str, str], field: str) -> str:
        values = [getattr(o, field) for o in results[key]]
        if isinstance(values[0], Score):
            values = [s.saved for s in values]
        return f"{median(values):g}"

    reached = results[("ours", MODES[0])][0].strict.reached
    print(f"STAND-IN evaluation · dataset '{store.name}' · {len(seeds)} seeds")
    if "fake" in store.name:
        print("FAKE DATA: these numbers only show the pipeline works. Don't quote them.")
    print(f"\nVulnerable people whose home the fire reached: {reached}")
    print(f"  {cannot_count(store.population, windows)} of them can never count under the "
          "strict rule: no satellite saw their\n  block clear after the fire began, so the "
          "fire may have been there from the start.")

    print("\nPicked up before the fire reached their home, median over seeds, strict / lenient")
    print("(strict = before the earliest plausible arrival, the headline; lenient = before the")
    print("first evidence of fire). Wait for orders = vehicles only go once a real order covers")
    print("the home, as on the night. True fire path = a perfect forecast (hindsight).\n")
    print(f"  {'':17}" + "".join(f"{m:>18}" for m in MODES))
    for name in PLANNERS:
        cells = [med((name, m), "strict") + " / " + med((name, m), "lenient") for m in MODES]
        print(f"  {name:17}" + "".join(f"{c:>18}" for c in cells))

    print("\nWhere the pickups went, with our forecast (median):\n")
    print(f"  {'':17}{'in time':>9}{'too late':>10}{'fire never came':>17}")
    for name in PLANNERS:
        key = (name, MODES[0])
        print(f"  {name:17}{med(key, 'in_time'):>9}{med(key, 'too_late'):>10}"
              f"{med(key, 'fire_never_came'):>17}")

    print("\nSame seed = same people known at the same times; only the planner differs.")
    print("With our forecast, strict:\n")
    print("  seed   ours   rule   ours - rule")
    ours, rule = results[("ours", MODES[0])], results[("dispatcher rule", MODES[0])]
    diffs = []
    for seed, o, r in zip(seeds, ours, rule, strict=True):
        diffs.append(o.strict.saved - r.strict.saved)
        print(f"  {seed:>4} {o.strict.saved:>6} {r.strict.saved:>6} {diffs[-1]:>+13}")
    print(f"\n  median difference {median(diffs):+g} (range {min(diffs):+} to {max(diffs):+})")


if __name__ == "__main__":
    main()
