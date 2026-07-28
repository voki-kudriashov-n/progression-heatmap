# Databricks

Databricks integration is prepared but not active.

The current dashboard reads only:

```text
data/sample_heatmap_data.csv
```

There are no Databricks SQL queries, jobs, tables, clusters, warehouses, hosts, credentials, or deployment resources in this first version.

## Future Integration Plan

The intended path is:

1. Keep local CSV loading as the default development path.
2. Add a Databricks-backed raw attempt data source behind `src/progression_heatmap/data.py`.
3. Preserve the raw dataframe contract used by `filters.py`, `metrics.py`, and `heatmap.py`.
4. Add environment-specific config only after the user explicitly approves real Databricks access.

Future data sources may use Databricks SQL or Databricks tables, but they should provide the same raw fields used by the local CSV: `client_time`, `user_id`, `balance_id`, `traffic_type`, `payer_type`, `failed`, `attempt`, `platform_name`, `first_attempt`, `FW`, `CW`, `CF`, `FF`, `reason_seg`, `partition_date`, and `level_cohort`.

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
