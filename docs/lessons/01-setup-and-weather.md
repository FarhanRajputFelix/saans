# Lesson 1: Project setup and weather ingestion

**Goal of this step:** a clean project skeleton, and six years of hourly weather for all five cities sitting on disk, ready to merge with air quality and fire data.

We start with weather for two reasons: Open-Meteo needs no API key, and it is almost gap-free, so it becomes the backbone timeline that every other source is attached to.

**Result:** 266,760 hourly records (5 cities × 53,352 hours × 13 variables), every expected hour present, plus one real data-quality finding (section 4).

---

## 1. Why the project is laid out this way

```
saans/config.py       one place for cities, dates, folders, keys
saans/ingest/         one module per data source
data/raw/             exactly what the API sent, never edited
data/interim/         parsed into tidy tables
data/processed/       cleaned, merged, model-ready
```

**Raw data is read-only.** If a cleaning step turns out to be wrong, you fix the code and re-run it. You never open a CSV and fix a number by hand, because then nobody (including you, next week) can reproduce the result. Keeping raw data untouched is also what makes the Data Quality Report possible: "rows received" is counted from `raw/`, "rows kept" from `processed/`.

**Code lives in a package, not one giant notebook.** Each stage is a module you can re-run on its own (`python -m saans.ingest.weather`). Notebooks come later, for exploring data and making charts, and they import from the package instead of copying code.

**`config.py` is the single source of truth.** If the instructor asks "what if you add Gujranwala?", you add one line there and every script picks it up.

**Secrets go in `.env`, never in code.** `load_dotenv()` reads `.env` into environment variables and `os.getenv("OPENAQ_API_KEY")` reads them back. `.gitignore` keeps `.env` off GitHub. Bots scan GitHub for leaked keys within minutes of a push.

**The virtual environment lives outside OneDrive** (`C:\Users\Laptronics.co\.venvs\saans`). A venv holds ~30,000 files; OneDrive would try to sync every one and can lock files mid-install.

## 2. How an API call works

An API call is a URL with parameters. This is the exact request the script makes, cut down to one day:

```
https://archive-api.open-meteo.com/v1/archive
  ?latitude=31.5497&longitude=74.3436          Lahore
  &start_date=2024-11-07&end_date=2024-11-07
  &hourly=wind_speed_10m,boundary_layer_height
  &timezone=GMT&wind_speed_unit=ms
```

The server answers with JSON shaped like this:

```json
{"latitude": 31.528997, "longitude": 74.38995, "elevation": 222.0,
 "hourly": {"time": ["2024-11-07T00:00", ...],
            "wind_speed_10m": [1.63, ...],
            "boundary_layer_height": [35.0, ...]}}
```

`hourly` is already column-shaped (one list per variable), so `pd.DataFrame(payload["hourly"])` turns it straight into a table. See `load_raw()` in [weather.py](../../saans/ingest/weather.py).

Two habits from the downloader you will reuse for every source:

- **Respect rate limits.** Open-Meteo allows 600 "calls" per minute, and one year of 13 variables counts as about 34 calls. The script pauses 5 seconds between requests, and if the server still answers `429 Too Many Requests` it waits a minute and retries.
- **Make downloads idempotent.** Each city-year is saved to its own file, and the script skips files that already exist. If the internet drops at Multan 2023, re-running fetches only what is missing.

## 3. Time: store UTC, convert late

Each source uses a different clock. OpenAQ gives UTC timestamps, NASA FIRMS gives UTC as an `HHMM` integer (`845` means 08:45), and Open-Meteo gives whatever you ask for. We ask for GMT and store everything in **UTC**.

Pakistan time (PKT = UTC+5) is applied only where humans care about the local clock: hour-of-day features (rush hour, night), event dates (a school closure is announced for a local date), and the dashboard.

Why it matters: if weather were stored in PKT and sensor readings in UTC, every join would shift by 5 hours, and the model would "see" evening rush-hour pollution at midnight. That bug produces no error message, just a quietly worse model.

## 4. What ERA5 is, and what it is not

Open-Meteo's history is **ERA5 reanalysis**: a weather model re-run over the past and continuously corrected with real observations (stations, balloons, satellites). The result is a best estimate of the atmosphere on a grid of about 25 km.

- **Strength:** almost no gaps, and the same method for every city and every year.
- **Limitation:** one value per ~25 km box. The API snapped Lahore's centre (31.5497, 74.3436) to the grid point (31.529, 74.390). Street-level effects such as the urban heat island are smoothed out. Say this in the report's limitations section.

### What the ingestion summary caught

The script ends by counting missing cells per city. Every city showed exactly **4,368** missing cells. That is 182 days × 24 hours, which is too round to be random. Digging in:

- Only `boundary_layer_height` is affected, from 1 Jan to 30 Jun 2024, identically in all five cities.
- Requesting the same hours from every model Open-Meteo offers (`era5`, `era5_seamless`, `ecmwf_ifs`, and others) returns the same hole, so it is a gap in the provider's archive, not a bug in our code.
- It matters: January 2024 is part of the 2023-24 smog season, which is training data.

The lesson: **trust, but count.** The documentation suggested the data was complete; one summary line proved otherwise. The finding is logged in [reports/data_quality_log.md](../../reports/data_quality_log.md) and gets fixed on the cleaning days (the plan is to impute it from the other weather variables and test that imputation on 2023, where the truth is known).

## 5. The weather variables that drive smog

**Wind direction is where the wind comes FROM.** 90 degrees means an east wind, blowing from east to west. This convention matters on Day 4: the Upwind Fire Exposure Index uses the angle θ between the wind's "from" direction and the bearing to each fire. When they match (cos θ = 1), smoke is carried straight at the city.

**Boundary layer height (BLH) is the lid.** On a sunny afternoon the ground heats the air, it rises and mixes, and pollution spreads through a layer 1 to 2 km deep. On a cold, clear winter night the ground cools fastest, a temperature inversion forms, and the layer can collapse to a few tens of metres. The same emissions squeezed into a layer 30 times thinner give roughly 30 times the concentration.

**Humidity** helps fine particles grow and linger. It also makes cheap optical sensors over-read PM2.5, which is why Day 3 applies the EPA humidity correction.

Lahore on 7 November 2024, the record smog week, at 05:00 PKT:

| Variable | Value | Meaning |
|---|---|---|
| Boundary layer height | 35 m | Lid lower than a 12-storey building |
| Wind speed (10 m) | 1.6 m/s | Nearly calm, no flushing |
| Wind direction | 113 degrees (ESE) | Blowing from the Indian Punjab and Haryana burning belt |
| Relative humidity | 94% | Damp air, particles grow and stay suspended |

All three ingredients of the proposal's model show up in four numbers: stagnation, upwind fires, and humidity.

## 6. Try it yourself

Activate the environment, start Python from the repo root, and load the table:

```python
import pandas as pd
w = pd.read_parquet("data/interim/weather_hourly.parquet")
w["time_pkt"] = w.time_utc.dt.tz_convert("Asia/Karachi")
lahore = w[w.city == "lahore"]
```

Try each exercise before opening the answer.

**Exercise 1: read a raw response.** Paste the URL from section 2 into your browser (as one line, no spaces). What was the boundary layer height at `2024-11-07T00:00`? Then open `data/raw/open_meteo/lahore_2024.json` in VS Code and find the same structure.

<details><summary>Answer</summary>

35 m. The raw file has exactly the same shape, just with 8,784 hours (2024 is a leap year).
</details>

**Exercise 2: how often was the lid shut?** In November 2024, for how many hours was Lahore's boundary layer below 50 m?

```python
nov = lahore[(lahore.time_pkt >= "2024-11-01") & (lahore.time_pkt < "2024-12-01")]
(nov.boundary_layer_height < 50).sum(), len(nov)
```

<details><summary>Answer</summary>

325 of 720 hours, or 45% of the month. The lowest value, 10 m, appears 35 times. 10 m is the model's floor, so read it as "10 m or less".
</details>

**Exercise 3: the city breathes once a day.** What is Lahore's median boundary layer height for each hour of the day (PKT) in November?

```python
lahore[lahore.time_pkt.dt.month == 11].groupby(lahore.time_pkt.dt.hour).boundary_layer_height.median()
```

<details><summary>Answer</summary>

30 to 50 m from 18:00 to 08:00, rising to about 990 m at 14:00, then collapsing to 65 m by 17:00. That is a 30-fold swing every day. Two consequences for the model: hour of day must be a feature, and children walking to school at 08:00 are still under a lid only 30 to 50 m high.
</details>

**Exercise 4: why does Karachi breathe easier?** Compare monthly median boundary layer height and wind speed for Lahore and Karachi.

```python
w["month"] = w.time_pkt.dt.month
w[w.city.isin(["lahore", "karachi"])].groupby(["city", "month"])[["boundary_layer_height", "wind_speed_10m"]].median().unstack(0)
```

<details><summary>Answer</summary>

| Month | Lahore BLH | Karachi BLH | Lahore wind | Karachi wind |
|---|---|---|---|---|
| Jun | 315 m | 740 m | 2.1 m/s | 6.0 m/s |
| Oct | 70 m | 370 m | 1.8 m/s | 3.6 m/s |
| Nov | 60 m | 195 m | 1.7 m/s | 3.0 m/s |
| Dec | 55 m | 195 m | 1.6 m/s | 2.9 m/s |

The sea breeze gives Karachi roughly twice the wind and three times the lid height. Multiply the two and you get the **ventilation coefficient** (BLH × wind speed), a standard air-quality index: in November Lahore scores about 100 m²/s and Karachi about 585, so Karachi's air is flushed roughly six times faster. This index goes into the stagnation feature on Day 4.
</details>

**Exercise 5: was 2024 windier from India?** For October and November of each year, what share of hours did Lahore's wind blow from 60 to 150 degrees (the sector of the Indian Punjab and Haryana burning belt)?

```python
on = lahore[lahore.time_pkt.dt.month.isin([10, 11])]
on.wind_direction_10m.between(60, 150).groupby(on.time_pkt.dt.year).mean()
```

<details><summary>Answer</summary>

| 2020 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| 24% | 30% | 30% | 25% | **37%** | 19% |

2024, the record smog season, had the most wind from the burning belt. One year is a hint, not proof: Day 4's Upwind Fire Exposure Index combines wind direction with actual fire counts, intensity and distance, and the model then tests whether it predicts PM2.5.
</details>

**Exercise 6: see idempotency for yourself.** Add a sixth city to `CITIES` in `config.py`:

```python
City("gujranwala", "Gujranwala", 32.1877, 74.1945),
```

Re-run `python -m saans.ingest.weather`. Only Gujranwala is downloaded; the other 35 files are skipped. Then delete the line and re-run: the table goes back to 266,760 rows, because the table is built from `CITIES`, not from whatever files happen to be on disk.

## 7. Be ready to explain (viva checkpoint)

- Why raw data is never edited, and how that supports the Data Quality Report.
- Why every timestamp is stored in UTC, and the silent bug that mixing clocks causes.
- What ERA5 reanalysis is, and its 25 km limitation.
- What the boundary layer is, and why winter nights are the worst hours.
- The "wind FROM" convention and why the fire index depends on it.

## Next

Day 1 continues with **OpenAQ**: first a coverage check (how many sensors, with how many years of PM2.5, in each city). That check is the project's first risk gate, because it tells us whether Faisalabad and Multan have enough history to model.
