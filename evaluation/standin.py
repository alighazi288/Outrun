"""STAND-IN evaluation: does our planner get more people out before the fire than the
dispatcher rule?

    uv run python -m evaluation.standin          # or: make eval

Headline metric (EVAL_SPEC §7): of the vulnerable residents whose hex the fire reached, the
share picked up before the fire's EARLIEST plausible arrival (strict). The lenient count,
against the LATEST plausible arrival (first evidence of fire), is printed beside it. Both
planners get identical everything (same data, same people known at the same times, same
safety rule); only the planner differs.

The arrival window comes from `evaluation/arrival_window.py`: DINS for which hexes burned,
VIIRS passes for when they were last seen clear and first seen burning, published reports
for the hours before the first satellite pass.

What makes this a stand-in:
- 5 random draws (seeds) of who is known and when (who's on the registry, when each person
  calls), on one fixed population. The real version: 30 synthetic populations per setting,
  plus the settings sweep.
- On fake data the numbers mean nothing. They only show the pipeline works.
"""

from __future__ import annotations

import argparse
import statistics
from datetime import datetime

from backend.clock import parse_t
from backend.replay import Replay
from backend.schemas import Resident
from backend.store import DataStore
from engines.routing import plan_routes, plan_routes_dispatcher
from evaluation.arrival_window import (
    ArrivalWindow,
    Score,
    build_windows,
    fire_start_of,
    load_dins,
)
from evaluation.arrival_window import score as score_window

PLANNERS = {"ours": plan_routes, "dispatcher rule": plan_routes_dispatcher}


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


def run(seeds: list[int]) -> dict[str, list[tuple[Score, Score]]]:
    """Per planner and seed: (strict, lenient) scores. A seed is a draw of who is known when."""
    results: dict[str, list[tuple[Score, Score]]] = {name: [] for name in PLANNERS}
    for seed in seeds:
        store = DataStore.from_env(seed=seed)
        windows = arrival_windows(store)
        for name, planner in PLANNERS.items():
            final = Replay(store, planner=planner).run()[-1]
            results[name].append((
                score_window(store.population, final.picked_up, windows, strict=True),
                score_window(store.population, final.picked_up, windows, strict=False),
            ))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seeds", type=int, default=5, help="draws of who is known and when")
    args = parser.parse_args()
    seeds = list(range(args.seeds))

    dataset = DataStore.from_env().name
    results = run(seeds)
    ours, rule = results["ours"], results["dispatcher rule"]
    print(f"STAND-IN evaluation · dataset '{dataset}'")
    if "fake" in dataset:
        print("FAKE DATA: these numbers only show the pipeline works. Don't quote them.")
    print("\nPeople picked up before the fire reached their home, out of the vulnerable people")
    print("it reached. strict = before the earliest plausible arrival (headline);")
    print("lenient = before the first evidence of fire. Same seed = same people known at the")
    print("same times; only the planner differs.\n")
    print("  seed  reached   ours strict/lenient   rule strict/lenient   ours - rule (strict)")
    diffs = []
    for seed, (o_s, o_l), (r_s, r_l) in zip(seeds, ours, rule, strict=True):
        diffs.append(o_s.saved - r_s.saved)
        print(f"  {seed:>4}  {o_s.reached:>7}   {o_s.saved:>8} / {o_l.saved:<8}  "
              f"{r_s.saved:>8} / {r_l.saved:<8}  {diffs[-1]:>+10}")
    median = statistics.median
    print(f"\n  strict median: ours {median(s.saved for s, _ in ours):g}, "
          f"dispatcher rule {median(s.saved for s, _ in rule):g}, "
          f"difference {median(diffs):+g} (range {min(diffs):+} to {max(diffs):+})")


if __name__ == "__main__":
    main()
