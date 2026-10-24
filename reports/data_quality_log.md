# Data Quality Log

A running record of every data issue found, as it is found, with its evidence and fix. On Day 3 this becomes the Data Quality Report (before and after statistics for every cleaning step).

## Records received

| Source | Rows received | Notes |
|---|---|---|
| Open-Meteo (ERA5) | 266,760 hourly rows (53,352 per city × 5), 13 variables | Every expected hour present, 1 Jan 2020 to 31 Jan 2026 UTC |
| OpenAQ | pending | |
| NASA FIRMS | pending | |
| News events | pending | |

## Findings

| ID | Source | Finding | Evidence | Fix | Status |
|---|---|---|---|---|---|
| W1 | Open-Meteo | `boundary_layer_height` missing from 2024-01-01 00:00 to 2024-06-30 23:00 UTC in all 5 cities | 4,368 hours × 5 cities = 21,840 cells. The same gap appears in every model checked on 2026-10-24: `best_match`, `era5`, `era5_seamless`, `ecmwf_ifs`, `ecmwf_ifs_analysis_long_window` | Impute from the 12 complete weather variables plus hour and month, using a model trained on other years. Validate by masking Jan to Jun 2023 and measuring the error. Add a `blh_imputed` flag column | open |
| W2 | Open-Meteo | Boundary layer height bottoms out at exactly 10 m | 35 hours in Lahore, Nov 2024, all at 10.0 m | Treat 10 m as "10 m or less" (a floor, not a measurement). Tree models are unaffected; note it in the report | noted |
