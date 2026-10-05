"""Pre-compute the whole replay into static files the dashboard can play back.

    uv run outrun-export                              # -> replay/
    uv run outrun-export --out dashboard/public/replay # for the dashboard dev server

Writes manifest.json, one WorldState JSON per step, and cells.geojson (the map hexagons).
The public prototype plays these files, so it is fast, free to host, and can't crash during
judging.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import h3

from backend.sim import Simulation
from backend.store import REPO_ROOT, DataStore


def cells_geojson(cells: list[str]) -> dict:
    """The outline of every map hexagon, so a web map can draw them.

    Steps name cells only by H3 id ("8929a1..."). This gives each id its six corners. The
    shapes never change during the night, so they are written once instead of in every step.
    GeoJSON wants [lon, lat] order (H3 gives (lat, lon)) and a closed ring (last = first).
    """
    features = []
    for cell in cells:
        ring = [[round(lon, 6), round(lat, 6)] for lat, lon in h3.cell_to_boundary(cell)]
        ring.append(ring[0])
        features.append({
            "type": "Feature",
            "properties": {"h3": cell},
            "geometry": {"type": "Polygon", "coordinates": [ring]},
        })
    return {"type": "FeatureCollection", "features": features}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "replay")
    parser.add_argument("--public", action="store_true",
                        help="for the judged demo: refuse unless every input is real")
    args = parser.parse_args()

    store = DataStore.from_env()
    if args.public and not store.complete:
        raise SystemExit(
            f"Refusing a public export of '{store.name}': synthetic={store.synthetic}, "
            f"borrowed from fake data: {store.fake_inputs}, not built: {store.missing_inputs}"
        )
    sim = Simulation(store)
    clock = store.make_clock()
    steps_dir = args.out / "steps"
    steps_dir.mkdir(parents=True, exist_ok=True)

    steps = []
    for i, t in enumerate(clock.times()):
        state = sim.world_state(t)
        name = f"steps/{i:04d}.json"
        (args.out / name).write_text(state.model_dump_json())
        steps.append({"i": i, "t": t.isoformat(), "file": name,
                      "unreachable": len(state.plan.unreachable),
                      "at_risk": sum(k.at_risk for k in state.risks)})
    (args.out / "cells.geojson").write_text(json.dumps(cells_geojson(store.cells)))
    manifest = {
        "dataset": store.name,
        "synthetic": store.synthetic,  # residents are always estimated; this is about inputs
        "fake_inputs": store.fake_inputs,
        "missing_inputs": store.missing_inputs,
        "start": clock.start.isoformat(),
        "end": clock.end.isoformat(),
        "step_minutes": int(clock.step.total_seconds() // 60),
        "cells": "cells.geojson",
        "steps": steps,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(steps)} steps and {len(store.cells)} map cells for dataset "
          f"'{store.name}' to {args.out}")
    if store.fake_inputs or store.missing_inputs:
        print(f"  NOT ALL REAL: borrowed from fake data {store.fake_inputs}, "
              f"not built yet {store.missing_inputs}")


if __name__ == "__main__":
    main()
