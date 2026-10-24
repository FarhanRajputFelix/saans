"""Hourly weather from the Open-Meteo Historical Weather API (no key needed).

Open-Meteo serves ERA5 reanalysis: a physics model re-run over the past and corrected with real
observations, on a ~25 km grid. It is almost gap-free, so it becomes the backbone of the hourly
timeline that the air-quality and fire data are merged onto. Known hole: boundary_layer_height is
missing from Jan to Jun 2024 in every model Open-Meteo serves (see reports/data_quality_log.md).

Run from the repo root:
    python -m saans.ingest.weather

Writes:
    data/raw/open_meteo/<city>_<year>.json   one untouched API response per city and year
    data/interim/weather_hourly.parquet      all cities in one tidy table, timestamps in UTC

Downloads are skipped when the raw file already exists. Delete a file to fetch it again.
"""
import json
import time
from datetime import date
from pathlib import Path

import pandas as pd
import requests

from saans.config import CITIES, END_DATE, INTERIM, RAW, ROOT, START_DATE, City

URL = "https://archive-api.open-meteo.com/v1/archive"
VARIABLES = [
    "temperature_2m",         # deg C
    "relative_humidity_2m",   # %
    "dew_point_2m",           # deg C
    "precipitation",          # mm in the hour
    "surface_pressure",       # hPa
    "cloud_cover",            # %
    "wind_speed_10m",         # m/s
    "wind_direction_10m",     # degrees the wind blows FROM (0 = north, 90 = east)
    "wind_gusts_10m",         # m/s
    "wind_speed_100m",        # m/s, less disturbed by buildings than 10 m wind
    "wind_direction_100m",    # degrees, FROM
    "shortwave_radiation",    # W/m2, sunlight that heats the ground and lifts the boundary layer
    "boundary_layer_height",  # m, the "lid" that traps pollution near the ground
]
RAW_DIR = RAW / "open_meteo"
OUT = INTERIM / "weather_hourly.parquet"
# A one-year request with 13 variables counts as ~34 API calls; the free limit is 600 calls/minute.
PAUSE_S = 5


def year_chunks(start: str, end: str):
    """Split the study period into calendar years: (year, first_day, last_day)."""
    s, e = date.fromisoformat(start), date.fromisoformat(end)
    for year in range(s.year, e.year + 1):
        yield year, max(s, date(year, 1, 1)), min(e, date(year, 12, 31))


def download(city: City, year: int, start: date, end: date) -> Path:
    path = RAW_DIR / f"{city.slug}_{year}.json"
    if path.exists():
        return path
    params = {
        "latitude": city.lat,
        "longitude": city.lon,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "hourly": ",".join(VARIABLES),
        "timezone": "GMT",          # store UTC; convert to Pakistan time only when needed
        "wind_speed_unit": "ms",    # m/s instead of the default km/h
    }
    for attempt in range(5):
        r = requests.get(URL, params=params, timeout=120)
        if r.status_code == 429:  # rate limited: wait a minute and retry
            print("    rate limited, waiting 60 s")
            time.sleep(60)
            continue
        r.raise_for_status()
        break
    else:
        raise RuntimeError(f"Open-Meteo kept rate-limiting {city.slug} {year}")
    path.write_text(r.text, encoding="utf-8")
    time.sleep(PAUSE_S)
    return path


def load_raw(path: Path, city: City) -> pd.DataFrame:
    payload = json.loads(path.read_text(encoding="utf-8"))
    df = pd.DataFrame(payload["hourly"])
    df["time"] = pd.to_datetime(df["time"], utc=True)  # requested in GMT, so tag it as UTC
    df.insert(0, "city", city.slug)
    return df.rename(columns={"time": "time_utc"})


def build_table() -> pd.DataFrame:
    frames = [load_raw(p, city) for city in CITIES.values()
              for p in sorted(RAW_DIR.glob(f"{city.slug}_*.json"))]
    df = pd.concat(frames, ignore_index=True)
    return df.sort_values(["city", "time_utc"]).reset_index(drop=True)


def summarize(df: pd.DataFrame) -> None:
    expected = len(pd.date_range(START_DATE, f"{END_DATE} 23:00", freq="h"))
    print(f"\n{len(df):,} hourly records, {df.shape[1] - 2} weather variables")
    for slug, g in df.groupby("city"):
        missing = int(g[VARIABLES].isna().sum().sum())
        print(f"  {slug:<11} {len(g):>7,} rows (expected {expected:,})  "
              f"{g.time_utc.min():%Y-%m-%d} to {g.time_utc.max():%Y-%m-%d %H:%M} UTC  missing cells: {missing}")


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    for city in CITIES.values():
        for year, start, end in year_chunks(START_DATE, END_DATE):
            print(f"  {city.name} {year}")
            download(city, year, start, end)
    df = build_table()
    df.to_parquet(OUT, index=False)
    summarize(df)
    print(f"\nSaved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
