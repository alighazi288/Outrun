"""Pre-compute the whole replay into static files the dashboard can play back.

    uv run outrun-export                              # -> replay/
    uv run outrun-export --out dashboard/public/replay # for the dashboard dev server

Writes manifest.json plus one WorldState JSON per step. The public prototype plays these
files, so it is fast, free to host, and can't crash during judging.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from backend.sim import Simulation
from backend.store import REPO_ROOT, DataStore


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "replay")
    args = parser.parse_args()

    store = DataStore.from_env()
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
    manifest = {
        "dataset": store.name,
        "synthetic_residents": True,
        "start": clock.start.isoformat(),
        "end": clock.end.isoformat(),
        "step_minutes": int(clock.step.total_seconds() // 60),
        "steps": steps,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(steps)} steps for dataset '{store.name}' to {args.out}")


if __name__ == "__main__":
    main()
