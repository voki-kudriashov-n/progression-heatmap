# Architecture

The dashboard is intentionally small and split into testable modules.

## Module Structure

- `src/progression_heatmap/app.py`: Streamlit UI, page layout, filter widgets, and chart rendering.
- `src/progression_heatmap/config.py`: Loads `config/dev.toml` or `config/prod.toml`.
- `src/progression_heatmap/data.py`: Defines the required raw attempt schema, validation, normalization, and local CSV loading helper.
- `src/progression_heatmap/data_sources.py`: Contains source adapters for local CSV, Databricks SQL warehouse, Spark SQL, and Spark tables.
- `src/progression_heatmap/filters.py`: Applies pre-group filters for level cohort, date, attempt group, payer type, traffic type, and platform, and stores metric selections.
- `src/progression_heatmap/metrics.py`: Groups filtered raw rows by `level_cohort` and `partition_date`, computes all grouped statistics, and selects one metric value plus hover/reliability context for rendering.
- `src/progression_heatmap/heatmap.py`: Converts selected metric rows into a `level_group` by `date` heatmap table.

## Data Flow

```text
selected project
  -> configured raw attempts source
  -> raw attempts schema contract
  -> pre-group filters
  -> group by level_cohort, partition_date
  -> grouped statistics
  -> metric_name / calculation_method selection
  -> heatmap preparation
  -> Streamlit rendering
```

The local source is `data/sample_heatmap_data.csv`. It mirrors the raw source table shape with columns such as `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

`data_sources.py` is the boundary between storage and analytics. CSV, Databricks SQL warehouse, Spark SQL, and Spark table adapters all return the same raw attempts dataframe contract. `filters.py`, `metrics.py`, and `heatmap.py` only depend on that contract.

Project selection happens before data loading. `MM` and `MyM` select different configured source entries. Locally both projects point to the CSV fixture for repeatable tests. In Databricks Apps, projects read their configured Unity Catalog tables through the SQL warehouse resource; the current MM smoke-test config points to `game_data_prod.analytics_voki.raw_objects_mm_test_users`.

The `auto` data source is deterministic, not a fallback chain. Outside Databricks Apps it resolves to CSV. Inside Databricks Apps it resolves to Databricks SQL warehouse and raises an explicit error if required App environment variables are missing.

The CSV source attempts local PySpark loading when Java and PySpark are available. If Java is unavailable, local development and tests use a pandas compatibility path.

## Grouping And Metric Selection

Pre-group filters are applied before aggregation:

- level cohort range
- partition date range
- attempt group (`1 attempt` or `2+ attempts`)
- payer type
- traffic type
- platform name

After that, `metrics.py` calculates grouped statistics by `level_cohort` and `partition_date`. The grouped statistics include absolute sums, wins, rates, partial rates, counts, and averages. The Streamlit app caches this grouped result based on pre-group filters. Changing `metric_name`, `calculation_method`, or the minimum observations threshold selects a precomputed statistic without recalculating the group by.

Percentage metrics carry `value_count`, `sample_count`, and `is_low_sample` context into Plotly. Cells below the selected minimum observations threshold are rendered with a gray overlay while preserving the underlying value in the hover label.

## Why UI And Business Logic Are Separated

The Streamlit app should stay thin so the core behavior can be tested without launching a browser or Streamlit runtime. Filter behavior, grouped metric calculations, and heatmap reshaping live outside `app.py`, so pytest can verify them quickly and reliably.

This separation keeps Databricks integration contained. The Databricks App uses the SQL warehouse adapter behind `data_sources.py` without rewriting Streamlit controls, filter behavior, grouped metric calculations, or heatmap preparation.
