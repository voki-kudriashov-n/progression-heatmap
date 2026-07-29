# Development

## Local Setup

```bash
make setup
```

This creates `.venv` and installs runtime and development dependencies.

## Run The Dashboard

Development config:

```bash
make run-dev
```

Production simulation config:

```bash
make run-prod
```

The production simulation config still reads the local CSV fixture. It does not connect to production systems.

## Test And Lint

```bash
make test
make lint
make check
```

Run `make check` after code changes. If it fails, fix the issue before considering the work complete.

## Working With Codex

Future Codex runs should:

- read `AGENTS.md` first
- keep UI logic separate from data sources, filtering, grouped metrics, and heatmap preparation logic
- update docs when architecture, commands, configs, data schema, Databricks workflow, or user-visible behavior changes
- avoid adding disallowed technologies unless the user explicitly approves them
- avoid real Databricks access unless the user explicitly asks for it

## Local PySpark Note

PySpark requires a working Java runtime. The project keeps PySpark in the dependency set for the intended local Spark path. When Java is available, the local CSV is loaded into a PySpark dataframe and grouped with Spark-compatible transformations. When Java is unavailable, the app and tests use a pandas compatibility path so local checks remain runnable.

## Data Source Boundary

Runtime data access goes through `progression_heatmap.data_sources`. The current configs use `CsvRawAttemptsDataSource`, while a future Databricks App can use `SparkSqlRawAttemptsDataSource` or `SparkTableRawAttemptsDataSource`. All source adapters must return the same raw attempt columns before processing starts.
