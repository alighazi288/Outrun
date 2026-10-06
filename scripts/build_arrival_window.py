"""Build `arrival_window.jsonl` for a dataset: when the fire plausibly reached each hex.

    uv run python scripts/build_arrival_window.py                 # OUTRUN_DATASET (fixtures)
    OUTRUN_DATASET=eaton uv run python scripts/build_arrival_window.py

Inputs, all from the dataset folder: `detections.jsonl` (VIIRS times), `fire_reports.jsonl`
(published report times), `evac_orders.jsonl` (the official order timeline, for warning lead
time), and `dins.geojson` if present (which buildings burned; never when). The rule is in
`evaluation/arrival_window.py`. The output is for scoring only; the replay never reads it.
"""

from __future__ import annotations

import json
import statistics

from backend.clock import parse_t
from backend.store import DataStore
from evaluation.arrival_window import (
    build_windows,
    load_dins,
    summary,
    warning_lead_min,
    warning_precision,
    write_windows,
)


def main() -> None:
    store = DataStore.from_env()
    replay = store.meta["replay"]
    fire_start = parse_t(store.meta.get("fire_start", replay["start"]))
    night_end = parse_t(replay["end"])
    dins_path = store.folder / "dins.geojson"
    dins = load_dins(dins_path)

    windows = build_windows(
        store.cells, store.detections, store.reports, dins, fire_start, night_end,
    )
    out = store.folder / "arrival_window.jsonl"
    write_windows(out, windows)

    print(f"Arrival window · dataset '{store.name}' → {out}")
    if store.synthetic:
        print("FAKE DATA: this file only shows the pipeline works. Don't quote it.")
    if not dins_path.exists():
        print("No dins.geojson in this folder: reached = detections and reports only.")
    print(json.dumps(summary(windows), indent=2, default=str))

    leads = [m for m in warning_lead_min(windows, store.orders).values() if m is not None]
    precision = warning_precision(store.cells, windows, store.orders)
    if leads:
        median = statistics.median(leads)
        print(
            f"Warning lead (order → earliest plausible arrival): median {median:.0f} min, "
            f"range {min(leads):.0f} to {max(leads):.0f}; {len(leads)}/{len(windows)} reached "
            "hexes were ever ordered"
        )
    if precision is not None:
        print(f"Warning precision: {precision:.0%} of ordered hexes were reached")


if __name__ == "__main__":
    main()
