# Common commands. Run `make help` to list them. Everything goes through uv.

# Load settings from .env if it exists (copy .env.example to start), and pass them to commands.
-include .env
export

.PHONY: help install test lint fix check api export view eval arrival-window check-data fixtures openapi fire-reports evac-orders clean

help:  ## List commands
	@grep -hE '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

install:  ## Install Python deps (add extras with: uv sync --group dev --extra routing)
	uv sync --group dev

test:  ## Run all tests
	uv run pytest -q

lint:  ## Check style
	uv run ruff check .

fix:  ## Auto-fix style where possible
	uv run ruff check . --fix

check: lint test  ## What CI runs: lint + tests

api:  ## Start the API on http://localhost:8000 (docs at /docs)
	uv run outrun-api

export:  ## Pre-compute the replay into replay/
	uv run outrun-export

view: export  ## Play the replay in the stand-in viewer: http://localhost:8001/scripts/viewer/
	@echo "Open http://localhost:8001/scripts/viewer/  (Ctrl+C to stop)"
	uv run python -m http.server 8001 --bind 127.0.0.1

eval:  ## Score our planner vs the dispatcher rule (STAND-IN; ~15 s)
	uv run python -m evaluation.standin

arrival-window:  ## Build arrival_window.jsonl (when fire reached each hex) for OUTRUN_DATASET
	uv run python scripts/build_arrival_window.py

fire-reports:  ## Build real Eaton fire_reports.jsonl from the published timelines
	uv run python scripts/build_fire_reports.py

evac-orders:  ## Build real Eaton evac_orders.jsonl (Genasys times, Lake Avenue split)
	uv run python scripts/build_evac_orders.py

check-data:  ## Check a dataset against the data contract (DATASET=eaton by default)
	uv run python -m backend.check_data $(or $(DATASET),eaton)

fixtures:  ## Regenerate the fake test data (same output every time)
	uv run python scripts/make_fake_data.py

openapi:  ## Refresh backend/openapi.json after changing an endpoint or schema
	uv run python scripts/export_openapi.py

clean:  ## Remove caches and generated replay files
	rm -rf .pytest_cache .ruff_cache replay data/runs
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
