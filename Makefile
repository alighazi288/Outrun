# Common commands. Run `make help` to list them. Everything goes through uv.

# Load settings from .env if it exists (copy .env.example to start), and pass them to commands.
-include .env
export

.PHONY: help install test lint fix check api export fixtures openapi clean

help:  ## List commands
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-9s %s\n", $$1, $$2}'

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

fixtures:  ## Regenerate the fake test data (same output every time)
	uv run python scripts/make_fake_data.py

openapi:  ## Refresh backend/openapi.json after changing an endpoint or schema
	uv run python scripts/export_openapi.py

clean:  ## Remove caches and generated replay files
	rm -rf .pytest_cache .ruff_cache replay data/runs
	find . -name __pycache__ -not -path './.venv/*' -prune -exec rm -rf {} +
