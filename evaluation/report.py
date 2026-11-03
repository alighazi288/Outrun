"""The evaluation's tables (EVAL_SPEC §7, §10, §13), from the runs evaluation/sweep.py wrote.

    uv run python -m evaluation.report      # prints them and writes evaluation/results/REPORT.md

Every number is a share of the vulnerable residents the fire reached who were picked up
before its earliest plausible arrival (strict), over the populations run so far: the median
and the 5th-95th percentile. Differences are paired: the same population under both planners.
"""

from __future__ import annotations

import argparse
import statistics
from collections import defaultdict
from pathlib import Path

from evaluation.sweep import BASELINE, POPULATIONS, RESULTS, TESTED, load, runs


def share(row: dict) -> float:
    return 100 * row["strict"] / row["reached"] if row["reached"] else 0.0


def spread(values: list[float]) -> tuple[float, float, float]:
    """(median, 5th, 95th percentile); one value: itself three times."""
    if not values:
        return float("nan"), float("nan"), float("nan")
    if len(values) == 1:
        return values[0], values[0], values[0]
    q = statistics.quantiles(values, n=20, method="inclusive")
    return statistics.median(values), q[0], q[-1]


def pct(values: list[float]) -> str:
    if not values:
        return "not run"
    m, lo, hi = spread(values)
    return f"{m:.1f}% ({lo:.1f}–{hi:.1f})"


class Results:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.by: dict[tuple[str, str, str, str], dict[int, dict]] = defaultdict(dict)
        for r in rows:
            self.by[(r["group"], r["label"], r["planner"], r["mode"])][r["population"]] = r

    def shares(self, group, label, planner, mode="our forecast") -> list[float]:
        return [share(r) for r in self.by[(group, label, planner, mode)].values()]

    def paired(self, a: tuple, b: tuple) -> list[float]:
        """Per population: a's share minus b's (percentage points), where both ran."""
        ra, rb = self.by[a], self.by[b]
        return [share(ra[k]) - share(rb[k]) for k in sorted(set(ra) & set(rb))]

    def metric(self, group, label, planner, name, mode="our forecast") -> list[float]:
        return [r[name] for r in self.by[(group, label, planner, mode)].values()
                if r.get(name) is not None]


def diff(values: list[float]) -> str:
    if not values:
        return "not run"
    m, lo, hi = spread(values)
    wins = sum(v > 0 for v in values) / len(values)
    return f"{m:+.1f} pp ({lo:+.1f} to {hi:+.1f}); ahead in {wins:.0%}"


def needed_for(curve: dict[int, list[float]], target: float = 90.0) -> str:
    """Smallest fleet where the median population gets at least target% out."""
    for n in sorted(curve):
        if curve[n] and statistics.median(curve[n]) >= target:
            return f"{n} vehicles"
    return f"not reached with {max(curve)} vehicles" if curve else "not run"


def report(rows: list[dict]) -> str:
    res = Results(rows)
    out: list[str] = []
    w = out.append
    planned: dict[str, int] = defaultdict(int)
    for r in runs():
        planned[r.group] += 1
    done: dict[str, int] = defaultdict(int)
    for r in rows:
        done[r["group"]] += 1
    pops = len({r["population"] for r in rows})

    w("# Evaluation results\n")
    w(f"{len(rows)} of {sum(planned.values())} runs done, over {pops} of {POPULATIONS} "
      "populations. Strict: picked up before the fire's earliest plausible arrival, as a share "
      "of the vulnerable residents the fire reached. Median (5th–95th percentile).\n")
    w("| Group | Runs done |\n| --- | --- |")
    for g, n in planned.items():
        w(f"| {g} | {done[g]} of {n} |")

    base = ("sweep", "baseline")
    w("\n## Baseline\n")
    w("| Planner | Mode | Picked up in time | Fire reached (people) |\n| --- | --- | --- | --- |")
    for (group, planner, mode) in [
        ("sweep", "ours", "our forecast"), ("sweep", "dispatcher rule", "our forecast"),
        ("extras", "closest first", "our forecast"), ("extras", "ours", "wait for orders"),
        ("extras", "dispatcher rule", "wait for orders"), ("extras", "ours", "true fire path"),
    ]:
        reached = res.metric(group, "baseline", planner, "reached", mode)
        people = f"{statistics.median(reached):.0f}" if reached else "not run"
        w(f"| {planner} | {mode} | {pct(res.shares(group, 'baseline', planner, mode))} "
          f"| {people} |")

    w("\n## What makes the difference (paired, percentage points)\n")
    w("| Comparison | Difference |\n| --- | --- |")
    ours_f, rule_f = (*base, "ours", "our forecast"), (*base, "dispatcher rule", "our forecast")
    ours_w = ("extras", "baseline", "ours", "wait for orders")
    rule_w = ("extras", "baseline", "dispatcher rule", "wait for orders")
    for text, a, b in [
        ("Ours vs the dispatcher rule (both with our forecast)", ours_f, rule_f),
        ("Our forecast vs waiting for the real orders (ours)", ours_f, ours_w),
        ("Our forecast vs waiting for the real orders (the rule)", rule_f, rule_w),
    ]:
        w(f"| {text} | {diff(res.paired(a, b))} |")

    w("\n## One setting at a time\n")
    w("| Setting | Ours | Dispatcher rule | Ours − rule |\n| --- | --- | --- | --- |")
    for name, values in TESTED.items():
        for v in values:
            label = "baseline" if getattr(BASELINE, name) == v else f"{name}={v:g}"
            ours = res.shares("sweep", label, "ours")
            rule = res.shares("sweep", label, "dispatcher rule")
            gap = res.paired(("sweep", label, "ours", "our forecast"),
                             ("sweep", label, "dispatcher rule", "our forecast"))
            tag = f"{name} = {v:g}" + (" (baseline)" if label == "baseline" else "")
            w(f"| {tag} | {pct(ours)} | {pct(rule)} | {diff(gap)} |")

    w("\n## Fleet size\n")
    w("| Vehicles | Ours, 25% known | Rule, 25% known | Ours, 100% known | Rule, 100% known |")
    w("| --- | --- | --- | --- | --- |")
    curves: dict[str, dict[int, list[float]]] = {"ours": {}, "dispatcher rule": {}}
    for n in TESTED["fleet"]:
        cells = [pct(res.shares("sweep", f"fleet={n}", p)) for p in curves]
        full = [res.shares("fleet_curve", f"fleet={n}", p) for p in curves]
        for p, values in zip(curves, full, strict=True):
            curves[p][n] = values
        w(f"| {n} | {cells[0]} | {cells[1]} | {pct(full[0])} | {pct(full[1])} |")
    w(f"\nVehicles needed for 90% (100% known, median population): ours "
      f"{needed_for(curves['ours'])}; dispatcher rule {needed_for(curves['dispatcher rule'])}.")

    w("\n## Good night, bad night, and checks\n")
    w("| Run | Ours | Dispatcher rule |\n| --- | --- | --- |")
    for group, label, text in [
        ("good_night", "good night", "Good night: every condition at its optimistic end"),
        ("bad_night", "bad night", "Bad night: every condition at its pessimistic end"),
        ("p5", "percentile=5", "Safety rule at the 5th percentile instead of the 10th"),
        ("equal_weights", "equal weights", "Equal priority weights for every need"),
    ]:
        w(f"| {text} | {pct(res.shares(group, label, 'ours'))} "
          f"| {pct(res.shares(group, label, 'dispatcher rule'))} |")

    w("\n## Other measures at the baseline (median)\n")
    w("| Measure | Ours | Dispatcher rule |\n| --- | --- | --- |")
    for name, text, fmt in [
        ("first_dispatch_min", "First vehicle moving (minutes after 6 p.m.)", "{:.0f}"),
        ("vehicle_use", "Vehicle use (share of vehicle-steps busy)", "{:.0%}"),
        ("escalated", "People escalated to fire command (ever)", "{:.0f}"),
        ("escalated_fire_reached", "… of them, the fire reached", "{:.0f}"),
        ("driver_exposure_min", "Driver exposure (vehicle-minutes; target 0)", "{:.0f}"),
    ]:
        cells = []
        for p in ("ours", "dispatcher rule"):
            values = res.metric("sweep", "baseline", p, name)
            cells.append(fmt.format(statistics.median(values)) if values else "not run")
        w(f"| {text} | {cells[0]} | {cells[1]} |")

    ours = res.shares(*base, "ours")
    rule = res.shares(*base, "dispatcher rule")
    waited = res.shares("extras", "baseline", "ours", "wait for orders")
    if ours and rule:
        m, lo, hi = spread(ours)
        w("\n## The sentence (EVAL_SPEC §13)\n")
        w(f"> Under stated assumptions, across {len(ours)} synthetic populations, {m:.1f}% "
          f"(5–95%: {lo:.1f}–{hi:.1f}%) of vulnerable residents in areas the fire reached were "
          f"picked up before its earliest plausible arrival, vs {spread(rule)[0]:.1f}% for the "
          "dispatcher rule" + (f" and {spread(waited)[0]:.1f}% when vehicles waited for the "
                               "real evacuation orders." if waited else "."))
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--results", type=Path, default=RESULTS)
    args = parser.parse_args()
    text = report(load(args.results))
    print(text)
    (args.results / "REPORT.md").write_text(text)


if __name__ == "__main__":
    main()
