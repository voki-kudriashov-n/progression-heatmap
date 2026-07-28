# Progression Heatmap

Progression Heatmap is a small Streamlit dashboard for Match-3 game analytics. It starts with local raw attempt-level CSV fixture data, groups it by level cohort and partition date, and shows a selected metric as an interactive heatmap.

## Stack

- Python 3.12
- Streamlit
- Plotly for interactive heatmap rendering and zooming
- pyspark, with a pandas fallback when a local Java runtime is unavailable
- pandas
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

Run the production simulation config:

```bash
make run-prod
```

The production config still uses the local sample CSV. It is not a real production connection.

## Tests And Linting

```bash
make test
make lint
make check
```

`make check` runs linting and tests.

## Current Limitations

- Data comes from `data/sample_heatmap_data.csv`, which mirrors the expected raw source table shape.
- The sample data covers `level_cohort` values `0..900` and daily `partition_date` values across 2026.
- There are no real Databricks SQL queries or production connections.
- The dashboard has no browser-based UI tests yet.
- Local PySpark loading requires a working Java runtime; without Java, the app uses a pandas compatibility path for local development and tests.

## Current Metric Flow

The local CSV is loaded as raw attempt rows with fields such as `payer_type`, `traffic_type`, `platform_name`, `failed`, `attempt`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `partition_date`, and `level_cohort`.

Pre-group filters:

- `level_cohort` range
- `partition_date` range
- `payer_type`
- `traffic_type`
- `platform_name`

After those filters, grouped statistics are calculated by `level_cohort` and `partition_date`. Metric selection then chooses a precomputed statistic, such as `CF / relative`, `failed / absolute`, `fail_rate / relative`, `win_rate / relative`, `attempt / average`, or `first_attempt / relative`, without recalculating the group by.

## Future Databricks Plan

The repository includes a minimal `databricks.yml` for future Databricks Asset Bundles work. Databricks integration is not active yet. Later versions can add a Databricks-backed data source behind the existing `data.py` interface, keeping the Streamlit UI and heatmap logic stable.

Do not commit Databricks credentials, tokens, secrets, host URLs, or production workspace details.
