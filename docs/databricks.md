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

`config/prod.toml` uses the Databricks App smoke-test source:

```toml
data_source = "auto"
default_project = "MM"
databricks_warehouse_id_env = "DATABRICKS_WAREHOUSE_ID"

[projects.MM]
csv_path = "data/sample_heatmap_data.csv"
databricks_table = "game_data_prod.analytics_voki.raw_objects_mm_test_users"

[projects.MyM]
csv_path = "data/sample_heatmap_data.csv"
databricks_table = "game_data_prod.analytics_voki.raw_objects_mym"
```

`config/prod.toml` currently points MM to `game_data_prod.analytics_voki.raw_objects_mm_test_users` for Databricks App smoke testing. Switch it back to `game_data_prod.analytics_voki.raw_objects_mm` after the app startup and SQL warehouse path are verified.

`auto` resolves to:

- `csv` outside Databricks Apps.
- `databricks_sql` inside Databricks Apps.

There are no fallbacks between these modes. If the app is in Databricks mode and the warehouse id or service principal environment variables are missing, startup/querying fails with an explicit error.

In Databricks mode the app does not fetch the full raw table into Streamlit. Filter bounds, attempt groups, and distinct filter values are collected with one SQL warehouse query, grouped metric statistics are pushed down to a second query after the user selects filters, and only compact result sets are returned to pandas for rendering.

The Databricks SQL aggregation returns `wins_absolute`, `fails_absolute`, percentage denominators, and the selected metric context needed for hover details and low-sample shading. The `1 attempt` / `2+ attempts` filter is pushed into the SQL `where` clause.

The sidebar shows a small Diagnostics panel with the resolved source, project, table, and current loading stage. The app also writes INFO logs to Databricks App logs. Useful markers are `app.filter_options.start`, `databricks_sql.filter_options.connect.start`, `databricks_sql.filter_options.execute.start`, `databricks_sql.filter_options.fetch.start`, `app.statistics.start`, and the matching `.done` or `.error` lines.

The notebook materializes `objects` as Unity Catalog tables with the same raw fields used by the local CSV: `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

The table names are intentionally configured per project. The project selector chooses the source table; it is not implemented as a filter inside one shared table.

`notebooks/source update.ipynb` writes the app-facing raw tables with `saveAsTable`:

- `game_data_prod.analytics_voki.raw_objects_mm`
- `game_data_prod.analytics_voki.raw_objects_mym`

When the notebook runs in test-users mode, it writes separate `_test_users` tables instead of overwriting the app-facing tables. The current MM App smoke test reads `game_data_prod.analytics_voki.raw_objects_mm_test_users`.

## Unity Catalog Permissions

Databricks Apps query data as the app's dedicated service principal. Access from a notebook usually uses the notebook user's identity or a different compute identity, so notebook write access does not automatically grant the app read access.

The app service principal needs:

- `Can use` on the connected SQL warehouse resource.
- `USE CATALOG` on the parent catalog.
- `USE SCHEMA` on the parent schema.
- `SELECT` on the configured project tables. For the current MM smoke test that means `game_data_prod.analytics_voki.raw_objects_mm_test_users`; for full data it means `game_data_prod.analytics_voki.raw_objects_mm` and `game_data_prod.analytics_voki.raw_objects_mym`.

Example grants:

```sql
GRANT USE CATALOG ON CATALOG game_data_prod TO `<app-service-principal>`;
GRANT USE SCHEMA ON SCHEMA game_data_prod.<schema_name> TO `<app-service-principal>`;
GRANT SELECT ON TABLE game_data_prod.analytics_voki.raw_objects_mm_test_users TO `<app-service-principal>`;
GRANT SELECT ON TABLE game_data_prod.analytics_voki.raw_objects_mm TO `<app-service-principal>`;
GRANT SELECT ON TABLE game_data_prod.analytics_voki.raw_objects_mym TO `<app-service-principal>`;
```

Replace `<app-service-principal>` with the service principal shown on the Databricks App Authorization tab.

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
