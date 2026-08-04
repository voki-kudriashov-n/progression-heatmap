# Development

## Local Setup

```bash
make setup
```

This creates `.venv` and installs runtime and development dependencies.

The codebase is kept compatible with Python 3.11 because Databricks Apps currently run this project on Python 3.11. Local development may still use Python 3.12 through the default `Makefile` setting.

## Run The Dashboard

Development config:

```bash
make run-dev
```

Production config locally:

```bash
make run-prod
```

The production config uses automatic source selection. On a local machine it reads the local CSV fixture. Inside Databricks Apps it uses the connected SQL warehouse.

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

Runtime data access goes through `progression_heatmap.data_sources`. Local runs use `CsvRawAttemptsDataSource`; Databricks App runs use the SQL warehouse adapter. Spark SQL and Spark table adapters are kept as prepared integration paths. All source adapters must return the same raw attempt columns before processing starts.

`data_source = "auto"` is environment-aware:

- local runtime -> CSV source
- Databricks App runtime -> Databricks SQL warehouse source

Project selection happens before loading data. Local tests map both `MM` and `MyM` to the CSV fixture. Databricks Apps read the table configured for the selected project.

Current pre-group aggregation filters are attempt group, platform, traffic type, and payer type. The dashboard applies staged filter changes to the graph only when the user clicks `Apply`. Level cohort range and date range are display filters applied after grouped statistics are cached. Percentage heatmap cells include numerator/sample counts in hover details and use gray shading when the sample count is below the selected threshold.
