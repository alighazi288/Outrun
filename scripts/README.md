# scripts/

Command-line scripts. Each writes files; none is imported by the backend.

| Script | What | Run |
|---|---|---|
| `make_fake_data.py` | The fake test dataset in `data/fixtures/eaton_fake/` (same output every time) | `make fixtures` |
| `export_openapi.py` | Writes `backend/openapi.json` for the dashboard and agents | `make openapi` |
| `build_*.py` | One per data card: writes a real file into `data/processed/eaton/` (see `data/BUILD.md`) | per card |
