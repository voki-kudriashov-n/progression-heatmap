# Databricks

Databricks integration is prepared but not active.

The current dashboard reads only:

```text
data/sample_heatmap_data.csv
```

The local fixture is intentionally kept below the Databricks App deployment source-file limit so the app can be smoke-tested before real data access is configured.

There are no active Databricks queries, jobs, tables, clusters, warehouses, hosts, credentials, or deployment resources in this first version.

## App Runtime

`app.yml` defines the Databricks App startup command:

```yaml
command:
  - "streamlit"
  - "run"
  - "src/progression_heatmap/app.py"
```

Databricks Apps automatically provide the Streamlit host and port environment variables, including `STREAMLIT_SERVER_ADDRESS=0.0.0.0`, `STREAMLIT_SERVER_PORT=8000`, and `STREAMLIT_SERVER_HEADLESS=true`. The manifest sets `PROGRESSION_HEATMAP_CONFIG=config/prod.toml` and `PYTHONPATH=src` so the app can run from the repository source layout in the Databricks App runtime.

The application code is kept Python 3.11-compatible for Databricks App runtime compatibility. Avoid Python 3.12-only syntax such as PEP 695 `type` alias statements.

## Future Integration Plan

The intended path is:

1. Keep local CSV loading as the default development path.
2. Use `src/progression_heatmap/data_sources.py` as the only storage boundary.
3. In a Databricks App, switch config to a Spark SQL or Spark table source that returns the required raw columns.
4. Preserve the raw dataframe contract used by `filters.py`, `metrics.py`, and `heatmap.py`.
5. Add environment-specific config only after the user explicitly approves real Databricks access.

Future data sources may use PySpark SQL or Spark tables, but they should provide the same raw fields used by the local CSV: `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

Example Databricks App config shape:

```toml
environment = "databricks"
data_source = "spark_sql"
spark_sql = """
select
  client_time,
  user_id,
  balance_id,
  traffic_type,
  payer_type,
  failed,
  attempt,
  platform_name,
  first_attempt,
  FW,
  CW,
  CF,
  FF,
  reason_seg,
  partition_date,
  level_cohort
from your_catalog.your_schema.raw_attempts
"""
app_title = "Match-3 Progression Heatmap"
```

If the source table already has the exact required columns, the lighter config can be:

```toml
environment = "databricks"
data_source = "spark_table"
spark_table = "your_catalog.your_schema.raw_attempts"
app_title = "Match-3 Progression Heatmap"
```

These examples are configuration shapes only. The repository still does not include real workspace details or production table names.

## Asset Bundles

`databricks.yml` defines only a bundle name and `dev` and `prod` targets. It does not define jobs or deployment resources.

You can run:

```bash
make validate-databricks-dev
```

This executes:

```bash
databricks bundle validate -t dev
```

The command may fail if the Databricks CLI is not installed or authenticated. That is an external setup step, not a local code failure.

## Safety Expectations

- Do not commit credentials, tokens, secrets, host URLs, or production workspace details.
- Do not connect to real production Databricks unless explicitly requested.
- Do not create Databricks jobs or deployment resources unless explicitly requested.
- Treat `config/prod.toml` as a production simulation until real access is approved.
