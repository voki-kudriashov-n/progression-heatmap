# Databricks

Databricks integration is active in code, but only when the dashboard runs inside Databricks Apps. Local runs keep using the CSV fixture.

Local runs read:

```text
data/sample_heatmap_data.csv
```

The local fixture is intentionally kept below the Databricks App deployment source-file limit so the app can be smoke-tested before real data access is configured.

Databricks App runs use the SQL warehouse resource configured with key `sql-warehouse`.

## App Runtime

`app.yml` defines the Databricks App startup command:

```yaml
command:
  - "streamlit"
  - "run"
  - "src/progression_heatmap/app.py"
```

Databricks Apps automatically provide the Streamlit host and port environment variables, including `STREAMLIT_SERVER_ADDRESS=0.0.0.0`, `STREAMLIT_SERVER_PORT=8000`, and `STREAMLIT_SERVER_HEADLESS=true`. The manifest sets `PROGRESSION_HEATMAP_CONFIG=config/prod.toml` and `PYTHONPATH=src` so the app can run from the repository source layout in the Databricks App runtime.

The manifest also maps the connected SQL warehouse resource into an environment variable:

```yaml
env:
  - name: "DATABRICKS_WAREHOUSE_ID"
    valueFrom: "sql-warehouse"
```

The application code is kept Python 3.11-compatible for Databricks App runtime compatibility. Avoid Python 3.12-only syntax such as PEP 695 `type` alias statements.

## Data Source Selection

Both `config/dev.toml` and `config/prod.toml` use:

```toml
data_source = "auto"
default_project = "MM"
databricks_warehouse_id_env = "DATABRICKS_WAREHOUSE_ID"

[projects.MM]
csv_path = "data/sample_heatmap_data.csv"
databricks_table = "raw_objects_mm"

[projects.MyM]
csv_path = "data/sample_heatmap_data.csv"
databricks_table = "raw_objects_mym"
```

`auto` resolves to:

- `csv` outside Databricks Apps.
- `databricks_sql` inside Databricks Apps.

There are no fallbacks between these modes. If the app is in Databricks mode and the warehouse id or service principal environment variables are missing, startup/querying fails with an explicit error.

The Databricks SQL source reads the same raw fields used by the local CSV: `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

The table names are intentionally configured per project. The project selector chooses the source table; it is not implemented as a filter inside one shared table.

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
- Do not connect to real production Databricks from local development unless explicitly requested.
- Do not create Databricks jobs or deployment resources unless explicitly requested.
- Keep local CSV as the local development and test source.
