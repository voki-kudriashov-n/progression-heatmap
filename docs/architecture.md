# Architecture

The dashboard is intentionally small and split into testable modules.

## Module Structure

- `src/progression_heatmap/app.py`: Streamlit UI, page layout, filter widgets, and chart rendering.
- `src/progression_heatmap/config.py`: Loads `config/dev.toml` or `config/prod.toml`.
- `src/progression_heatmap/data.py`: Loads raw attempt-level CSV data and validates the required source schema.
- `src/progression_heatmap/filters.py`: Applies pre-group filters for level cohort, date, payer type, traffic type, and platform, and stores metric selections.
- `src/progression_heatmap/metrics.py`: Groups filtered raw rows by `level_cohort` and `partition_date`, computes all grouped statistics, and selects one metric value for rendering.
- `src/progression_heatmap/heatmap.py`: Converts selected metric rows into a `level_group` by `date` heatmap table.

## Data Flow

```text
raw CSV
  -> schema validation
  -> raw type normalization
  -> pre-group filters
  -> group by level_cohort, partition_date
  -> grouped statistics
  -> metric_name / calculation_method selection
  -> heatmap preparation
  -> Streamlit rendering
```

The active source is `data/sample_heatmap_data.csv`. It mirrors the raw source table shape with columns such as `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

`data.py` attempts local PySpark loading when Java and PySpark are available. Grouping and metric calculations are written against Spark-compatible operations so the later Databricks path can reuse the same logic. If Java is unavailable, local development and tests use a pandas compatibility path.

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

This separation also keeps the future Databricks integration contained. A later Databricks-backed loader can be added behind `data.py` without rewriting the Streamlit controls or heatmap preparation code.
