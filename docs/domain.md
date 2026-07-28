# Domain

This project supports Match-3 game analytics. Match-3 games are level-based puzzle games where progression quality is often inspected by grouping levels and comparing metric behavior across time.

Current projects:

- MyM: Mystery Matters
- MM: Manor Matters

## Fields

- `client_time`: event timestamp for the raw attempt row.
- `user_id`: player identifier in the raw source table.
- `balance_id`: level or balance identifier from the source row.
- `traffic_type`: acquisition source segment, used as a pre-group filter.
- `payer_type`: payer segment, used as a pre-group filter.
- `failed`: raw failure flag.
- `attempt`: attempt number for the level.
- `platform_name`: platform segment, used as a pre-group filter.
- `first_attempt`: raw first-attempt flag.
- `FW`, `CW`, `CF`, `FF`: raw indicator columns for far win, close win, close fail, and far fail.
- `reason_seg`: source reason segment.
- `partition_date`: date used on the heatmap X axis. The local sample data covers each day of 2026.
- `level_cohort`: level cohort used on the heatmap Y axis. The local sample data covers `0..900`.
- `value`: selected grouped metric value displayed in the heatmap cell after aggregation.
- `metric_name`: selected metric, such as `CF`, `FW`, `attempts`, `fail_rate`, `win_rate`, or `first_attempt`.
- `calculation_method`: selected metric calculation, such as `absolute`, `relative`, `partial_relative`, or `average`.

## Reading The Heatmap

Each cell represents one selected grouped metric value for a `level_cohort` and `partition_date` after pre-group filters are applied. Higher and lower values are shown through the heatmap color scale so analysts can quickly scan for progression shifts across dates and level cohorts.
