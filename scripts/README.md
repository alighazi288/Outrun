# scripts/

Command-line scripts. Each writes files; none is imported by the backend. Plus `viewer/`, a
stand-in map that plays the replay until the real dashboard (`dashboard/`) is ready.

| Script | What | Run |
|---|---|---|
| `make_fake_data.py` | The fake test dataset in `data/fixtures/eaton_fake/` (same output every time) | `make fixtures` |
| `export_openapi.py` | Writes `backend/openapi.json` for the dashboard and agents | `make openapi` |
| `build_*.py` | One per data card: writes a real file into `data/processed/eaton/` (see `data/BUILD.md`) | per card |
| `build_fire_reports.py` | Real Eaton `fire_reports.jsonl` from the published timelines | `uv run python scripts/build_fire_reports.py` |
| `build_evac_orders.py` | Real Eaton `evac_orders.jsonl` from the alerts actually sent (LA County IPAWS layer) | `uv run python scripts/build_evac_orders.py` |
| `eaton_timeline.py` | Shared citations and geocoded places | imported by the two builders |
