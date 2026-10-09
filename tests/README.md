# tests/

Tests are the contract between folders. Each owner's code must pass them before merging.
Run everything with `make check` (what CI runs).

| Test file | Checks |
|---|---|
| `test_clock.py` | No hindsight: nothing from after time t is ever visible at t |
| `test_knowledge.py` | Every simulated help call traces back to a record published before it |
| `test_engines.py` | Every planner: nobody dropped, capacities respected, and the **driver-safety rule** on every route (the PRD's contract test) |
| `test_api.py` | Endpoints answer at the right times; tool names stay stable for Orchestrate |
| `test_schemas.py` | The shared data formats accept good records and reject bad ones |
| `test_eaton_reports.py` | Real fire reports and evacuation orders: citations, Lake Avenue split, precision |
