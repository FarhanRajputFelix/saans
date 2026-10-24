# SAANS: Smog Attribution And Nowcasting System

*Saans* means breath in Urdu.

SAANS forecasts PM2.5 24 and 48 hours ahead for five Pakistani cities, warns of hazardous days (AQI above 300 on the US EPA scale), explains every forecast with SHAP, and turns it into English and Urdu health advisories on an interactive dashboard.

Data Science course project, SZABIST University Karachi. Farhan Bashir (2312407). Submitted to Sir Ahsan Nisar.

**Live dashboard:** _link added after deployment_ · **Notebooks:** open any of them below on GitHub (outputs are saved) or in Colab with the badge at the top of each.

## Results at a glance

Models trained on 1 Jan 2020 to 28 Sep 2024; tested on two held-out smog seasons (October to January). Every number below is computed in [notebook 05](notebooks/05_models_shap.ipynb).

**Forecasting the next 24-hour mean PM2.5** (mean absolute error in ug/m3; lower is better)

| Test season | Cities | SAANS | Persistence | Seasonal average | Skill vs persistence |
|---|---|---|---|---|---|
| 2024-25, record season | Lahore, Islamabad, Karachi | **28.0** | 32.7 | 48.2 | **+14.4%** |
| 2025-26 | all five, incl. Faisalabad and Multan (never seen in training) | **25.4** | 25.8 | 68.5 | +1.6% |

The 48-hour forecast (the 24 hours after that): 38.0 vs 44.1 (+13.8%) and 34.6 vs 36.1 (+4.2%).

* **Lahore, 2024-25:** +17% over persistence. On 6 Nov 2024, when schools closed in 18 districts, SAANS forecast 386 ug/m3 a day ahead (observed: 510).
* **Unseen cities:** Faisalabad +14%, Multan +11%, with no training data from either city.
* **Weak spot:** Lahore 2025-26 (-40%). After the US monitor feed stopped in March 2025, Lahore's data come from low-cost networks that read differently, and the model over-forecasts by about 26 ug/m3. See [finding L1](reports/data_quality_log.md).

**Hazard warnings** (will the next 24 hours exceed AQI 300?)

| Test season | Method | Hit rate | False alarm ratio | F1 |
|---|---|---|---|---|
| 2024-25 | SAANS classifier | **92%** | 33% | **0.774** |
| 2024-25 | Persistence | 76% | 24% | 0.755 |
| 2025-26 | SAANS classifier | **92%** | 33% | **0.775** |
| 2025-26 | Persistence | 76% | 23% | 0.764 |

SAANS catches about 9 in 10 hazardous periods against 3 in 4 for persistence, at the cost of more false alarms (the threshold favours warnings, chosen on validation data).

**Other measured results:** weighting fires by wind direction raises the fire index's correlation with next-day PM2.5 from 0.30 to 0.38; the boundary-layer-height imputation scores r = 0.91 on a hidden half-year; LLM event extraction is 65% fully correct on a hand-checked sample of 20; 32 of 32 LLM advisories passed the automatic number check.

## The pipeline, notebook by notebook

| # | Notebook | What it does |
|---|---|---|
| 01 | [Data ingestion](notebooks/01_data_ingestion.ipynb) | Loads the four sources and checks what arrived: sensor coverage per city, fire detections per month, headlines per season, raw record counts |
| 02 | [Data cleaning](notebooks/02_data_cleaning.ipynb) | The nine cleaning steps, each with its reason, rule and before/after counts; writes the hourly master table and the [Data Quality Report](reports/data_quality_report.md) |
| 03 | [LLM event calendar](notebooks/03_llm_event_calendar.ipynb) | Gemini turns 2,255 real news headlines into a calendar of smog measures; a random 20 are checked by hand |
| 04 | [Features](notebooks/04_features.ipynb) | Upwind Fire Exposure Index (decay length tuned on training data), Stagnation Index, lags, calendar; strictly no future information |
| 05 | [Models and SHAP](notebooks/05_models_shap.ipynb) | Persistence and seasonal baselines, LightGBM 24 h / 48 h forecasts with an 80% band, hazard classifier, SHAP driver groups, what-if on fires |
| 06 | [AI Smog Explainer](notebooks/06_llm_advisories.ipynb) | Gemini writes English and Urdu advisories from the model's numbers only, with an automatic number check |

The downloaders live in [`saans/ingest/`](saans/ingest/) and are run once from the command line; everything after that is in the notebooks. The dashboard is [`app/streamlit_app.py`](app/streamlit_app.py).

## Data

| Source | What | Records received |
|---|---|---|
| [Open-Meteo Historical Weather](https://open-meteo.com/en/docs/historical-weather-api) (ERA5) | 13 hourly variables per city, incl. boundary layer height | 266,760 hourly rows |
| [OpenAQ v3](https://docs.openaq.org/) | Hourly PM2.5 from 200 sensors (reference monitors and low-cost networks) within 25 km of each city | 587,969 sensor-hours |
| [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov/) | VIIRS (S-NPP) and MODIS fire detections over Punjab, Haryana and Sindh | 1,184,817 detections |
| [GDELT](https://www.gdeltproject.org/) | Pakistani smog headlines, Oct-Jan of every season | 2,255 headlines |

About **2.04 million raw records** in total, 1 Jan 2020 to 31 Jan 2026. Cities: Lahore, Faisalabad, Multan, Islamabad and Karachi (Karachi is in Sindh; it stays in as a coastal contrast city).

Committed to this repo so every notebook runs without API keys: the parsed tables (`data/interim/`), the cleaned master table and features (`data/processed/`), the LLM answer cache (`data/llm_cache/`), the trained models (`models/`) and the dashboard data (`app/data/`). The raw API responses (`data/raw/`) are not committed; the downloaders rebuild them.

## Run it yourself

```powershell
python -m venv $HOME\.venvs\saans                # outside OneDrive, so the environment is not synced
& $HOME\.venvs\saans\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env                            # paste your API keys (only needed to re-download or re-run the LLM)

# optional: re-download everything (~2 hours, mostly NASA FIRMS)
python -m saans.ingest.weather
python -m saans.ingest.openaq coverage; python -m saans.ingest.openaq hours
python -m saans.ingest.firms
python -m saans.ingest.news

jupyter notebook notebooks/                       # run 01 to 06 in order
streamlit run app/streamlit_app.py                # the dashboard
```

## Repository layout

```
notebooks/        01-06: the analysis, with outputs saved
saans/            Python package: config, downloaders (ingest/), AQI, LLM client, chart style
app/              Streamlit dashboard + its precomputed data
data/interim/     parsed source tables          data/processed/  master table, features, events
data/llm_cache/   cached LLM answers            models/          trained LightGBM models
reports/          Data Quality Report, evaluation tables, event-extraction check, figures
docs/lessons/     study notes
```

## Study notes

1. [Project setup and weather ingestion](docs/lessons/01-setup-and-weather.md)
2. [How SAANS works, and how to defend it](docs/lessons/02-viva-guide.md)

The [findings log](reports/data_quality_log.md) records every data surprise met along the way, with evidence and fix.
