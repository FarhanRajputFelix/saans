# SAANS data: where everything is

| Folder / file | What it is | Made by |
|---|---|---|
| `raw/` | Untouched API responses (not on GitHub: large and re-downloadable) | `saans/ingest/*.py` |
| `interim/weather_hourly.parquet` | Open-Meteo ERA5 weather, 266,760 hourly rows | `saans/ingest/weather.py` |
| `interim/openaq_hourly.parquet` | PM2.5 from 200 sensors, 587,969 sensor-hours, before cleaning | `saans/ingest/openaq.py` |
| `interim/openaq_pm10_hourly.parquet` | PM10 from the 5 sensors that report it | `saans/ingest/openaq.py pm10` |
| `interim/openaq_sensors.csv` | Every sensor near the five cities: location, provider, first/last reading | `saans/ingest/openaq.py coverage` |
| `interim/firms_fires.parquet` | NASA FIRMS fire detections, before cleaning | `saans/ingest/firms.py` |
| `interim/news_headlines.csv` | 2,255 GDELT smog headlines | `saans/ingest/news.py` |
| **`processed/master_hourly.parquet`** | **The cleaned hourly master table** (one row per city per hour) | notebook 02 |
| **`processed/csv/master_hourly_<city>.csv`** | **The same table as one CSV per city** (opens in Excel) | notebook 02 |
| **`processed/sample_lahore_1-7_nov_2024.csv`** | **One week of the cleaned table, small enough for GitHub to display** | notebook 02 |
| `processed/fires_clean.parquet` | Cleaned fire detections (low confidence, static sources and repeat passes removed) | notebook 02 |
| `processed/events.json`, `events.csv` | The LLM-extracted event calendar, each event with its source headline | notebook 03 |
| `processed/event_calendar.parquet` | Daily event flags per city | notebook 03 |
| `processed/features.parquet` | Model features and targets | notebook 04 |
| `llm_cache/` | Every LLM answer, so notebooks re-run without API calls | `saans/llm.py` |

The dashboard's **Cleaned data** tab shows the master table for any city and dates, with a CSV download.

## Columns of the master table

| Column | Meaning |
|---|---|
| `city` | lahore, faisalabad, multan, islamabad, karachi |
| `time_utc`, `time_pkt` | Start of the hour, in UTC and in Pakistan time (UTC+5) |
| `pm25` | Cleaned PM2.5 for the city, ug/m3 (reference monitor where one reports, else the median of low-cost sensors) |
| `pm25_source` | `reference`, `low-cost` or `interpolated` |
| `pm25_interpolated` | True if a gap of 3 hours or less was filled (never in the test seasons) |
| `gap_hours`, `long_gap` | Length of the missing stretch this hour sits in; `long_gap` = longer than 3 hours (left empty, never filled) |
| `n_low` | Number of low-cost sensors reporting that hour |
| `pm10` | PM10, ug/m3, where one of the 5 PM10 sensors reports (mostly Lahore and Karachi) |
| `extreme_event` | PM2.5 of 250 ug/m3 or more: genuine extremes are kept and tagged, never deleted |
| `fireworks_night` | New Year's Eve and Shab-e-Barat nights (approximate dates) |
| `temperature_2m`, `dew_point_2m` | Air temperature and dew point at 2 m, deg C |
| `relative_humidity_2m` | Relative humidity, % |
| `precipitation` | Rain in the hour, mm |
| `surface_pressure` | hPa |
| `cloud_cover` | % |
| `wind_speed_10m`, `wind_gusts_10m`, `wind_speed_100m` | m/s |
| `wind_direction_10m`, `wind_direction_100m` | Degrees the wind blows **from** (90 = from the east) |
| `shortwave_radiation` | Sunshine, W/m2 |
| `boundary_layer_height` | Height of the mixing layer, m (the "lid" that traps smog) |
| `blh_imputed` | True for Jan-Jun 2024, when the provider had no BLH and it was imputed (validated r = 0.91) |
| `fires_300km`, `frp_300km` | Cleaned fire detections within 300 km in that hour, and their total radiative power (MW) |
| `is_test_season` | True for Oct 2024-Jan 2025 and Oct 2025-Jan 2026, the held-out test seasons |

Missing values: `pm25` is empty where no valid measurement exists (see `gap_hours`). Faisalabad and Multan have PM2.5 only from June 2025.
