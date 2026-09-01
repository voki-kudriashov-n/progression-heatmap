# Progression Heatmap

Progression Heatmap is a small Streamlit dashboard for Match-3 game analytics. It starts with local raw attempt-level CSV fixture data, groups it by level cohort and partition date, and shows a selected metric as an interactive heatmap.

## Stack

- Python 3.11-compatible code; local development can use Python 3.12
- Streamlit
- Plotly for interactive heatmap rendering and zooming
- pyspark, with a pandas fallback when a local Java runtime is unavailable
- pandas
- Databricks SQL Connector and SDK for Databricks App warehouse access
- pytest
- ruff
- Databricks Asset Bundles configuration prepared for later use

## Setup

```bash
make setup
```

This creates `.venv` and installs the local package with development dependencies.

## Run Locally

```bash
make run-dev
```

Run the production config locally:

```bash
make run-prod
```

The production config uses `data_source = "auto"`. Locally it still reads the local sample CSV. Inside Databricks Apps it reads from the connected SQL warehouse.

## Databricks App Smoke Test

`app.yml` contains the Databricks App startup command for the Streamlit dashboard. It runs `src/progression_heatmap/app.py`; Databricks Apps provide the Streamlit host and port environment automatically, and the app uses `config/prod.toml`.

The app expects a SQL warehouse resource with key `sql-warehouse`. `app.yml` exposes it as `DATABRICKS_WAREHOUSE_ID`.

## Tests And Linting

```bash
make test
make lint
make check
```

`make check` runs linting and tests.

## Current Limitations

- Local runs read `data/sample_heatmap_data.csv`, which mirrors the expected raw source table shape.
- Databricks App runs read project-specific tables through the connected SQL warehouse. The current prod config maps `MM -> game_data_prod.analytics_voki.raw_objects_mm` and `MyM -> game_data_prod.analytics_voki.raw_objects_mm_test_users`.
- The sample data stays below the Databricks App source-file limit and covers `level_cohort` values `0..900` for daily `partition_date` values from `2026-01-01` through `2026-02-19`.
- The dashboard has no browser-based UI tests yet.
- Local PySpark loading requires a working Java runtime; without Java, the app uses a pandas compatibility path for local development and tests.

## Current Metric Flow

The local CSV is loaded as raw attempt rows with fields such as `payer_type`, `traffic_type`, `platform_name`, `super_ball`, `failed`, `attempt`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `partition_date`, and `level_cohort`.

Pre-group aggregation filters:

- `payer_type`
- `traffic_type`
- `platform_name`
- `attempt` group
- `super_ball`

After those filters, grouped statistics are calculated by `level_cohort` and `partition_date` only after the user clicks `Применить`. The app keeps the last 10 grouped tables in memory, keyed by project/source and these aggregation filters. The `level_cohort` range and `partition_date` range are applied to that cached grouped table at display time, so changing only date or level does not recalculate the group by. Metric selection then chooses a precomputed statistic, such as `CF / relative`, `failed / absolute`, `fail_rate / relative`, `win_rate / relative`, or `attempt / average`, without recalculating the group by. Low-sample percentage cells are hidden when `Минимум наблюдений` is greater than `0`, so hidden values do not affect the heatmap color gradient. The chart area also has a vertical `Диапазон градиента` scale that changes only Plotly `zmin`/`zmax` for the already prepared heatmap table.

## Databricks Data Path

The app routes data access through `progression_heatmap.data_sources`. Configured `data_source = "auto"` resolves to:

- `csv` outside Databricks Apps.
- `databricks_sql` inside Databricks Apps.

Project selection chooses a source entry before data loading. It is not a filter inside a shared table.

Do not commit Databricks credentials, tokens, secrets, host URLs, or production workspace details.
