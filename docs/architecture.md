# Architecture

The dashboard is intentionally small and split into testable modules.

## Module Structure

- `src/progression_heatmap/app.py`: Streamlit UI, page layout, filter widgets, and chart rendering.
- `src/progression_heatmap/config.py`: Loads `config/dev.toml` or `config/prod.toml`.
- `src/progression_heatmap/data.py`: Defines the required raw attempt schema, validation, normalization, and local CSV loading helper.
- `src/progression_heatmap/data_sources.py`: Contains source adapters for local CSV, Spark SQL, and Spark tables.
- `src/progression_heatmap/filters.py`: Applies pre-group filters for level cohort, date, payer type, traffic type, and platform, and stores metric selections.
- `src/progression_heatmap/metrics.py`: Groups filtered raw rows by `level_cohort` and `partition_date`, computes all grouped statistics, and selects one metric value for rendering.
- `src/progression_heatmap/heatmap.py`: Converts selected metric rows into a `level_group` by `date` heatmap table.

## Data Flow

```text
configured raw attempts source
  -> raw attempts schema contract
  -> pre-group filters
  -> group by level_cohort, partition_date
  -> grouped statistics
  -> metric_name / calculation_method selection
  -> heatmap preparation
  -> Streamlit rendering
```

The active source is `data/sample_heatmap_data.csv`. It mirrors the raw source table shape with columns such as `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

`data_sources.py` is the boundary between storage and analytics. CSV, Spark SQL, and Spark table adapters all return the same raw attempts dataframe contract. `filters.py`, `metrics.py`, and `heatmap.py` only depend on that contract, so migrating to a Databricks App should mostly mean switching the configured source and providing a PySpark query or table name.

The CSV source attempts local PySpark loading when Java and PySpark are available. Grouping and metric calculations are written against Spark-compatible operations so the Databricks path can reuse the same logic. If Java is unavailable, local development and tests use a pandas compatibility path.

## Grouping And Metric Selection

Pre-group filters are applied before aggregation:

- level cohort range
- partition date range
- payer type
- traffic type
- platform name

After that, `metrics.py` calculates grouped statistics by `level_cohort` and `partition_date`. The grouped statistics include absolute sums, rates, partial rates, counts, and averages. The Streamlit app caches this grouped result based on pre-group filters. Changing `metric_name` or `calculation_method` selects a precomputed statistic without recalculating the group by.

## Why UI And Business Logic Are Separated

The Streamlit app should stay thin so the core behavior can be tested without launching a browser or Streamlit runtime. Filter behavior, grouped metric calculations, and heatmap reshaping live outside `app.py`, so pytest can verify them quickly and reliably.

This separation also keeps Databricks integration contained. A Databricks App can use the Spark SQL or Spark table adapter behind `data_sources.py` without rewriting Streamlit controls, filter behavior, grouped metric calculations, or heatmap preparation.
