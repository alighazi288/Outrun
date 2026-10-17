"""Forecast scorecard (EVAL_SPEC §8): how good is the nowcast, judged by where the fire went.

    OUTRUN_DATASET=palisades uv run python -m evaluation.forecast_check   # the development set
    OUTRUN_DATASET=eaton uv run python -m evaluation.forecast_check       # the test set, once

At every scored step t the forecast sees only what existed at t (DataStore.at(t)). It is
judged against the arrival window (evaluation/arrival_window.py), which is hindsight.

For each horizon h (1, 2, 3 h) and every cell the fire had not been confirmed in by t:
- outcome 1: the window ends by t + h (fire confirmed there by then);
- outcome 0: it starts after t + h, or the fire never reached the cell;
- excluded: the window straddles t + h (we can't tell); the count is printed.

Printed:
- Brier score per horizon (mean squared error of the chance; 0 is perfect), beside the
  simple rule "100% within 2 km of any fire evidence seen so far, else 0".
- Flag precision: of cells flagged at risk (3-h chance >= AT_RISK_P3H), the share the fire
  reached within 3 h, and the share it ever reached. Recall: of cells it reached within 3 h,
  the share flagged.
- Safety: of cells the fire reached within 3 h, the share where it may have beaten the
  pessimistic arrival (earliest < t + arrival_p10) and where it surely did (latest < ...).
  The design aims for about 10%.
- Over-blocking: of cells the driver-safety rule closes at t (arrival_p10 within the safety
  margin), the share the fire did not reach within the next 2 h; and the average share of
  the whole map closed per step. On Oct 12 a version that looked safer on Palisades closed
  44% of Eaton's map per step and cut pickups from 115 to 20, so watch both.

Settings are chosen on the development set only. Eaton is the test set (EVAL_SPEC §12).
"""

from __future__ import annotations

import argparse
import statistics
from dataclasses import dataclass, field
from datetime import timedelta

import h3

from backend.assumptions import AT_RISK_P3H, SAFETY_MARGIN_MIN
from backend.clock import parse_t
from backend.store import DataStore
from engines import nowcast
from engines.travel import haversine_m
from evaluation.arrival_window import ArrivalWindow, build_windows, fire_start_of, load_dins

HORIZONS_H = (1, 2, 3)
BASELINE_KM = 2.0
BLOCK_CHECK_MIN = 120


@dataclass
class Tally:
    sq: dict[int, list[float]] = field(default_factory=lambda: {h: [] for h in HORIZONS_H})
    sq_base: dict[int, list[float]] = field(default_factory=lambda: {h: [] for h in HORIZONS_H})
    excluded: dict[int, int] = field(default_factory=lambda: dict.fromkeys(HORIZONS_H, 0))
    flagged: int = 0
    flagged_hit_3h: int = 0
    flagged_ever: int = 0
    hits_3h: int = 0
    hits_flagged: int = 0
    hits_with_p10: int = 0
    may_beat_p10: int = 0
    surely_beat_p10: int = 0
    blocked: int = 0
    blocked_no_fire: int = 0
    steps: int = 0
    cells: int = 0


def windows_for(store: DataStore) -> dict[str, ArrivalWindow]:
    return build_windows(
        store.cells, store.detections, store.reports, load_dins(store.folder / "dins.geojson"),
        fire_start_of(store.meta), parse_t(store.meta["replay"]["end"]),
    )


def score(store: DataStore, every_min: int, forecast=nowcast) -> Tally:
    windows = windows_for(store)
    clock = store.make_clock()
    centre = {c: h3.cell_to_latlng(c) for c in store.cells}
    tally = Tally(cells=len(store.cells))
    for t in clock.times():
        if (t - clock.start) % timedelta(minutes=every_min):
            continue
        snap = store.at(t)
        out = {o.h3: o for o in forecast(snap.detections, snap.wind, store.cells, t,
                                         snap.reports)}
        evidence = [(d.lat, d.lon) for d in snap.detections]
        evidence += [(r.lat, r.lon) for r in snap.reports]
        tally.steps += 1
        for c in store.cells:
            w = windows.get(c)
            if w is not None and w.latest <= t:
                continue  # already confirmed burning: nothing to forecast
            o = out.get(c)
            p = {1: o.p_1h, 2: o.p_2h, 3: o.p_3h} if o else dict.fromkeys(HORIZONS_H, 0.0)
            near = any(haversine_m(centre[c], e) <= BASELINE_KM * 1000 for e in evidence)
            for h in HORIZONS_H:
                end = t + timedelta(hours=h)
                if w is not None and w.earliest <= end < w.latest:
                    tally.excluded[h] += 1
                    continue
                y = 1.0 if (w is not None and w.latest <= end) else 0.0
                tally.sq[h].append((p[h] - y) ** 2)
                tally.sq_base[h].append((float(near) - y) ** 2)
            hit = w is not None and w.latest <= t + timedelta(hours=3)
            flagged = o is not None and o.p_3h >= AT_RISK_P3H
            if flagged:
                tally.flagged += 1
                tally.flagged_hit_3h += hit
                tally.flagged_ever += w is not None
            if hit:
                tally.hits_3h += 1
                tally.hits_flagged += flagged
                if o is not None and o.arrival_p10_min is not None:
                    tally.hits_with_p10 += 1
                    p10_at = t + timedelta(minutes=o.arrival_p10_min)
                    tally.may_beat_p10 += w.earliest < p10_at
                    tally.surely_beat_p10 += w.latest < p10_at
            if o is not None and (o.burning or (
                    o.arrival_p10_min is not None and o.arrival_p10_min <= SAFETY_MARGIN_MIN)):
                tally.blocked += 1
                fire_soon = w is not None and w.earliest <= t + timedelta(minutes=BLOCK_CHECK_MIN)
                tally.blocked_no_fire += not fire_soon
    return tally


def report(name: str, tally: Tally) -> None:
    def share(a: int, b: int) -> str:
        return f"{a / b:.0%} ({a:,}/{b:,})" if b else "n/a"

    print(f"Forecast scorecard · dataset '{name}' · {tally.steps} steps scored")
    print("\n  Brier score, lower is better (ours vs 'within 2 km of any evidence'):")
    for h in HORIZONS_H:
        ours = statistics.fmean(tally.sq[h]) if tally.sq[h] else float("nan")
        base = statistics.fmean(tally.sq_base[h]) if tally.sq_base[h] else float("nan")
        print(f"    {h} h: {ours:.4f} vs {base:.4f}   ({len(tally.sq[h]):,} cell-steps, "
              f"{tally.excluded[h]:,} excluded: window straddles t + {h} h)")
    print(f"\n  Flag precision (fire within 3 h):  {share(tally.flagged_hit_3h, tally.flagged)}")
    print(f"  Flag precision (fire ever came):   {share(tally.flagged_ever, tally.flagged)}")
    print(f"  Flag recall (fire within 3 h):     {share(tally.hits_flagged, tally.hits_3h)}")
    print(f"  Fire may have beaten the p10 time: {share(tally.may_beat_p10, tally.hits_with_p10)}")
    print(f"  Fire surely beat the p10 time:     "
          f"{share(tally.surely_beat_p10, tally.hits_with_p10)}   (design: about 10%)")
    print(f"  Closed to drivers, no fire within {BLOCK_CHECK_MIN} min: "
          f"{share(tally.blocked_no_fire, tally.blocked)}")
    closed = tally.blocked / (tally.steps * tally.cells) if tally.steps and tally.cells else 0
    print(f"  Map closed to drivers, average per step: {closed:.0%}   (the cost to rescues: "
          "a forecast that closes a downwind town stops every pickup there)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--every", type=int, default=30, help="score every N minutes")
    args = parser.parse_args()
    store = DataStore.from_env()
    report(store.name, score(store, args.every))


if __name__ == "__main__":
    main()
