PYTHON ?= python3.12
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
DEV_CONFIG := config/dev.toml
PROD_CONFIG := config/prod.toml

.PHONY: setup run-dev run-prod test lint check validate-databricks-dev

setup:
	$(PYTHON) -m venv $(VENV)
	$(VENV_PYTHON) -m pip install --upgrade pip
	$(VENV_PYTHON) -m pip install -e ".[dev]"

run-dev:
	PROGRESSION_HEATMAP_CONFIG=$(DEV_CONFIG) STREAMLIT_BROWSER_GATHER_USAGE_STATS=false $(VENV_PYTHON) -m streamlit run src/progression_heatmap/app.py --server.headless true

run-prod:
	PROGRESSION_HEATMAP_CONFIG=$(PROD_CONFIG) STREAMLIT_BROWSER_GATHER_USAGE_STATS=false $(VENV_PYTHON) -m streamlit run src/progression_heatmap/app.py --server.headless true

test:
	$(VENV_PYTHON) -m pytest

lint:
	$(VENV_PYTHON) -m ruff check .

check: lint test

validate-databricks-dev:
	databricks bundle validate -t dev
