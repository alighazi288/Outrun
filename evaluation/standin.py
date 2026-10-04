"""STAND-IN evaluation: does our planner get more people out before the fire than the
dispatcher rule?

    uv run python -m evaluation.standin          # or: make eval

Headline metric (EVAL_SPEC §7): of the vulnerable residents whose hex the fire reached, the
share picked up before the fire got there. Both planners get identical everything (same data,
same people known at the same times, same safety rule); only the planner differs.

What makes this a stand-in:
- Truth: a hex's fire arrival is the FIRST evidence of fire there (a satellite detection within
  375 m of its centre, or a fire report located in it). The real version builds a window from
  DINS damage, satellite passes and the report timelines, and scores against its EARLIEST
  time (strict); first evidence is the window's latest time, so this is the lenient end.
- 5 random draws (seeds) of who is known and when (who's on the registry, when each person
  calls), on one fixed population. The real version: 30 synthetic populations per setting,
  plus the settings sweep.
- On fake data the numbers mean nothing. They only show the pipeline works.
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass
from datetime import datetime

import h3

from backend.replay import Replay
from backend.schemas import Resident
from backend.store import DataStore
from engines.routing import plan_routes, plan_routes_dispatcher
from engines.travel import haversine_m

DETECTION_RADIUS_M = 375.0  # a VIIRS pixel; EVAL_SPEC §3

PLANNERS = {"ours": plan_routes, "dispatcher rule": plan_routes_dispatcher}


def fire_arrival(store: DataStore, hexes: set[str]) -> dict[str, datetime]:
    """Hex -> first evidence of fire there. Uses the whole night (hindsight), so it's for
    scoring only, never for planning."""
    arrival: dict[str, datetime] = {}

    def seen(cell: str, when: datetime) -> None:
        if cell not in arrival or when < arrival[cell]:
            arrival[cell] = when

    for cell in hexes:
        centre = h3.cell_to_latlng(cell)
        for d in store.detections:
            if haversine_m(centre, (d.lat, d.lon)) <= DETECTION_RADIUS_M:
                seen(cell, d.observed_at)
    for r in store.reports:
        if r.h3 in hexes:
            seen(r.h3, r.reported_at)
    return arrival


@dataclass
class Score:
    reached: int  # vulnerable residents whose hex the fire reached
    saved: int  # of those, picked up before the fire got there


def score(population: list[Resident], picked_up: dict[str, datetime],
          arrival: dict[str, datetime]) -> Score:
    """One count per resident record; `none` needs excluded (EVAL_SPEC §7)."""
    reached = [r for r in population if r.needs != "none" and r.h3 in arrival]
    saved = [r for r in reached if r.id in picked_up and picked_up[r.id] < arrival[r.h3]]
    return Score(reached=len(reached), saved=len(saved))


def run(seeds: list[int]) -> dict[str, list[Score]]:
    """Score every planner on every seed (a draw of who is known and when)."""
    results: dict[str, list[Score]] = {name: [] for name in PLANNERS}
    for seed in seeds:
        store = DataStore.from_env(seed=seed)
        arrival = fire_arrival(store, {r.h3 for r in store.population})
        for name, planner in PLANNERS.items():
            final = Replay(store, planner=planner).run()[-1]
            results[name].append(score(store.population, final.picked_up, arrival))
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
    print("it reached. Same seed = same people known at the same times; only the planner")
    print("differs.\n")
    print("  seed   reached   ours   dispatcher rule   ours - rule")
    diffs = []
    for seed, o, r in zip(seeds, ours, rule, strict=True):
        diffs.append(o.saved - r.saved)
        print(f"  {seed:>4}   {o.reached:>7}   {o.saved:>4}   {r.saved:>15}   {diffs[-1]:>+11}")
    median = statistics.median
    print(f"\n  median: ours {median(s.saved for s in ours):g}, "
          f"dispatcher rule {median(s.saved for s in rule):g}, "
          f"difference {median(diffs):+g} (range {min(diffs):+} to {max(diffs):+})")


if __name__ == "__main__":
    main()
