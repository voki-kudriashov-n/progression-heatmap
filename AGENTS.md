# AGENTS.md

## Project Purpose

This repository contains a small Streamlit dashboard for Match-3 progression analytics. The local fixture is a raw attempt-level CSV that is grouped into heatmap metrics by level cohort and partition date.

Current projects:

- MyM: Mystery Matters
- MM: Manor Matters

## Approved Technology Stack

- Python 3.12
- Streamlit for the dashboard UI
- Plotly for interactive heatmap rendering and zooming
- pyspark for local CSV data loading and transformations when a local Java/Spark runtime is available
- pandas for in-process tabular objects returned to the app and tests
- pytest for tests
- ruff for linting
- pyproject.toml for Python project configuration
- Makefile for repeatable local commands
- Databricks CLI and Databricks Asset Bundles only as a prepared future integration layer

## Disallowed Unless Explicitly Approved

- React
- FastAPI
- real Databricks SQL queries
- databases
- Docker
- cloud deployment
- MCP integrations
- production Databricks access
- production credentials, tokens, or secrets

## Project Structure

```text
.
├── README.md
├── AGENTS.md
├── Makefile
├── pyproject.toml
├── databricks.yml
├── config/
│   ├── dev.toml
│   └── prod.toml
├── data/
│   └── sample_heatmap_data.csv
├── docs/
│   ├── architecture.md
│   ├── development.md
│   ├── domain.md
│   └── databricks.md
├── src/
│   └── progression_heatmap/
│       ├── __init__.py
│       ├── app.py
│       ├── config.py
│       ├── data.py
│       ├── data_sources.py
│       ├── filters.py
│       ├── metrics.py
│       └── heatmap.py
└── tests/
    ├── test_data.py
    ├── test_filters.py
    └── test_heatmap.py
```

The Python package uses `progression_heatmap` because Python imports cannot use hyphens.

## Commands Codex Should Use

- `make setup`: create `.venv` and install dependencies.
- `make run-dev`: run the dashboard with `config/dev.toml`.
- `make run-prod`: run the dashboard with `config/prod.toml`, which is only a production simulation.
- `make test`: run pytest.
- `make lint`: run ruff.
- `make check`: run lint and tests.
- `make validate-databricks-dev`: run `databricks bundle validate -t dev`.

## Verification Policy

- After every code change, run `make check`.
- If `make check` fails, keep fixing until it passes.
- Do not claim completion while local tests or lint are failing.
- Browser-based UI tests are not required in the first version.
- If Databricks validation fails because the Databricks CLI is missing or auth is not configured, report that as an external setup step, not a code failure.

## Documentation Policy

Update documentation when changing:

- architecture
- commands
- configuration
- data schema
- Databricks workflow
- user-visible behavior

Do not create noisy documentation updates for tiny internal refactors that do not change behavior.

## Databricks Safety Rules

- Databricks integration is prepared but inactive.
- Do not connect to real production Databricks unless the user explicitly asks.
- Do not add credentials, tokens, host URLs, secrets, or production workspace details.
- Do not create Databricks jobs or deployment resources without explicit approval.
- Keep local CSV as the active data source until the user requests Databricks data access.

## Design And Architecture Rules

- Keep UI logic separate from data and heatmap logic.
- Keep `app.py` focused on Streamlit layout and controls.
- Keep runtime data access in `data_sources.py`.
- Keep raw schema validation and normalization in `data.py`.
- Keep filtering logic in `filters.py`.
- Keep grouped metric calculations in `metrics.py`.
- Keep heatmap preparation logic in `heatmap.py`.
- Keep the dashboard practical, analytical, and easy to scan.
