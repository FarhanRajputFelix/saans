# SAANS: Smog Attribution And Nowcasting System

*Saans* means breath in Urdu.

SAANS forecasts PM2.5 24 and 48 hours ahead for five Pakistani cities, flags hazardous days (AQI above 300 on the US EPA scale), explains each forecast with SHAP, and turns the result into plain English and Urdu advisories on a dashboard.

Data Science course project, SZABIST University Karachi. Farhan Bashir (2312407). Submitted to Sir Ahsan Nisar.

## Progress

| Day | Work | Status |
|---|---|---|
| 1 | Ingestion: weather, air quality, fires, news events; sensor coverage check | weather done |
| 2 | Cleaning I: time alignment, units, duplicates, sensor faults, glitch vs real event | |
| 3 | Cleaning II: humidity correction, fire cleaning, gaps, hourly master table, Data Quality Report | |
| 4 | Features: Upwind Fire Exposure Index, stagnation index, lags, event calendar (frozen at end of day) | |
| 5 | Models: persistence baseline, LightGBM 24 h and 48 h, hazard classifier, SHAP | |
| 6 | AI Smog Explainer (LLM), Streamlit dashboard | |
| 7 | Deploy, final report, slides | |

## Data sources

| Source | What | Key |
|---|---|---|
| [Open-Meteo Historical Weather](https://open-meteo.com/en/docs/historical-weather-api) | Hourly ERA5 weather per city, incl. boundary layer height | none |
| [OpenAQ v3](https://docs.openaq.org/) | Hourly PM2.5, PM10, NO2 from reference and low-cost sensors | free |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | VIIRS and MODIS satellite fire detections | free MAP_KEY |
| News reports | Smog emergencies, school closures, traffic bans, fireworks nights (LLM-extracted) | n/a |

Study period: 1 Jan 2020 to 31 Jan 2026. Models train on the 2020 to 2023 smog seasons and are tested on the 2024 and 2025 seasons (October to January).

Cities: Lahore, Faisalabad, Multan, Islamabad and Karachi. Karachi is in Sindh rather than Punjab; it stays in as a contrast city, coastal and far from the crop-burning belt.

## Setup (Windows)

```powershell
python -m venv $HOME\.venvs\saans          # outside OneDrive, so the environment is not synced
& $HOME\.venvs\saans\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                       # then paste your API keys into .env
```

## Run

From the repo root, with the environment active:

```powershell
python -m saans.ingest.weather     # ~5 min the first time, instant afterwards
```

## Layout

```
saans/            Python package: all pipeline code
  config.py       cities, study period, folders, API keys (one place to change settings)
  ingest/         Day 1: download each source into data/raw/
data/             git-ignored; rebuilt by the scripts
  raw/            untouched API responses, never edited
  interim/        parsed into tidy tables
  processed/      cleaned, merged, model-ready
docs/lessons/     step-by-step notes explaining each stage
reports/          Data Quality Report, evaluation tables, figures
```

## Lessons

1. [Project setup and weather ingestion](docs/lessons/01-setup-and-weather.md)
