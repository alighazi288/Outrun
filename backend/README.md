# backend/

The replay clock, the FastAPI app, and the OpenAPI tools the agents call. It also holds the pieces
every other folder imports:

| File | What |
|---|---|
| `schemas.py` | The shared data formats (Resident, Vehicle, FireOutlook, Plan, Decision, FireReport, Facility...). One place, so everyone's code fits together |
| `assumptions.py` | Every assumed number, labeled (sourced, from the brief, or placeholder) with the range the evaluation tests. Nothing assumed is hard-coded anywhere else |
| `clock.py` | Replay clock and the "only data from before time t" filter |
| `knowledge.py` | Who the planner knows about, and from when (registry vs. help calls). See `docs/EVAL_SPEC.md` §4 |
| `store.py`, `sim.py` | Loads a dataset; runs one step of the loop (nowcast → risk → plan) |
| `api/main.py` | REST + WebSocket. Each endpoint's `operation_id` is a tool name for Orchestrate |
| `openapi.json` | The exported API contract for the dashboard and agents (`make openapi`) |

`backend`, `engines` and `evaluation` are packages in one Python project (`pyproject.toml`), so
`from backend.schemas import Resident` works everywhere.
