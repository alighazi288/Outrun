# Common commands. Run `make help` to list them. Everything goes through uv.

# Load settings from .env if it exists (copy .env.example to start), and pass them to commands.
-include .env
export

.PHONY: help install test lint fix check api live export replay-bundle view live-pull live-fires live-area eval forecast-check arrival-window check-data fixtures openapi fire-reports evac-orders roads dins clean

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

live:  ## Start the live server on http://localhost:8001 (any US area, today's data)
	uv run outrun-live

export:  ## Pre-compute the replay into dashboard/public/replay (set OUTRUN_DATASET=eaton for real data)
	uv run outrun-export

replay-bundle:  ## Save the Eaton replay as dashboard/replay.tar.gz
	OUTRUN_DATASET=eaton uv run outrun-export
	COPYFILE_DISABLE=1 tar --no-xattrs -czf dashboard/replay.tar.gz -C dashboard/public replay

view: export  ## Play the replay in the dashboard: http://localhost:5173
	npm --prefix dashboard install --no-audit --no-fund
	npm --prefix dashboard run dev

live-pull:  ## What is live over an area right now: fire, wind, alerts (DATASET=eaton)
	uv run python -m backend.feeds --dataset $(or $(DATASET),eaton)

live-fires:  ## US wildfires still burning right now (NIFC)
	uv run python -m backend.area --fires

live-area:  ## Set up any US area from national data: make live-area LAT=39.76 LON=-121.62 NAME=paradise
	uv run python -m backend.area --lat $(LAT) --lon $(LON) --name $(NAME)

eval:  ## Score the planners vs waiting for orders and a perfect forecast (SEEDS=5; no sweep yet)
	uv run python -m evaluation.standin --seeds $(or $(SEEDS),5)

forecast-check:  ## Score the fire forecast (DATASET=palisades to choose settings; eaton once)
	OUTRUN_DATASET=$(or $(DATASET),palisades) uv run python -m evaluation.forecast_check

arrival-window:  ## Build arrival_window.jsonl (when fire reached each hex) for OUTRUN_DATASET
	uv run python scripts/build_arrival_window.py

fire-reports:  ## Build real Eaton fire_reports.jsonl from the published timelines
	uv run python scripts/build_fire_reports.py

evac-orders:  ## Build real Eaton evac_orders.jsonl from the real alerts (LA County IPAWS layer)
	uv run python scripts/build_evac_orders.py

roads:  ## Build real Eaton road travel times (needs: uv sync --group dev --extra routing)
	uv run python scripts/build_roads.py

dins:  ## Build Eaton dins.geojson: which buildings burned (scoring only)
	uv run python scripts/build_dins.py

check-data:  ## Check a dataset against the data contract (DATASET=eaton by default)
	uv run python -m backend.check_data $(or $(DATASET),eaton)

fixtures:  ## Regenerate the fake test data (same output every time)
	uv run python scripts/make_fake_data.py

openapi:  ## Refresh backend/openapi.json after changing an endpoint or schema
	uv run python scripts/export_openapi.py

clean:  ## Remove caches and generated replay files
	rm -rf .pytest_cache .ruff_cache replay data/runs
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
