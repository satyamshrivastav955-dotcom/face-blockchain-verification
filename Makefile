.PHONY: help install install-dev models test lint format typecheck check web assets screenshots demo clean

PY ?= python

help:  ## list targets
	@grep -E '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## runtime dependencies, pinned to the tested versions
	$(PY) -m pip install -r requirements.txt -c constraints.txt

install-dev:  ## + lint, types, web API and in-process EVM test deps
	$(PY) -m pip install -r requirements-dev.txt -c constraints.txt

models:  ## download the permissively licensed OpenCV Zoo models (checksum-verified)
	$(PY) scripts/fetch_models.py

test:  ## hermetic test suite (no network, keys, wallet or gas)
	$(PY) -m pytest tests -q

lint:  ## ruff lint + format check
	$(PY) -m ruff check src tests scripts
	$(PY) -m ruff format --check src tests scripts

format:  ## apply ruff formatting and safe fixes
	$(PY) -m ruff check --fix src tests scripts
	$(PY) -m ruff format src tests scripts

typecheck:  ## mypy
	$(PY) -m mypy

check: lint typecheck test  ## everything CI runs for the Python side

web:  ## build the frontend
	cd web && npm ci && npm run build

assets:  ## regenerate the README SVGs (the benchmark chart is drawn from docs/results/lfw_benchmark.json)
	$(PY) scripts/make_readme_assets.py

screenshots:  ## regenerate README screenshots and GIF from the live app (needs playwright + a built frontend)
	$(PY) scripts/capture_screenshots.py

demo:  ## local-only demo: no network, no keys, no gas
	$(PY) -m src.main register --image tests/data/query.png --fixture tests/data/candidates.json \
		--engine stub --allow-offline-stub --dry-run
	$(PY) -m src.main verify --record output/verification.json --dry-run

clean:  ## remove caches and build output (never touches records, evidence or models)
	rm -rf .pytest_cache .mypy_cache .ruff_cache web/dist
	find . -name __pycache__ -type d -not -path "./web/node_modules/*" -prune -exec rm -rf {} +
