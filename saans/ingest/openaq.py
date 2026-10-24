"""Hourly air quality from the OpenAQ v3 API (free key in .env as OPENAQ_API_KEY).

Two stages:
  1. coverage: find every monitoring location within 25 km of each city and list its PM2.5,
     PM10 and NO2 sensors with their first and last reading. This is the Day 1 risk check.
  2. hours: download the hourly averages of every PM2.5 sensor that overlaps the study period.

Run from the repo root:
    python -m saans.ingest.openaq coverage
    python -m saans.ingest.openaq hours

Writes:
    data/raw/openaq/locations_<city>.json     untouched /locations responses
    data/raw/openaq/hours/sensor_<id>.json    every hourly result for one sensor
    data/interim/openaq_sensors.csv           one row per sensor (the coverage table)
    data/interim/openaq_hourly.parquet        all sensors in one tidy table, UTC
"""
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

from saans.config import CITIES, END_DATE, INTERIM, OPENAQ_API_KEY, RAW, ROOT, START_DATE

API = "https://api.openaq.org/v3"
RAW_DIR = RAW / "openaq"
HOURS_DIR = RAW_DIR / "hours"
SENSORS_CSV = INTERIM / "openaq_sensors.csv"
OUT = INTERIM / "openaq_hourly.parquet"
PARAMETERS = {"pm25", "pm10", "no2"}
RADIUS_M = 25_000  # the API maximum
PAGE = 1000
RETRY_CODES = {408, 429, 500, 502, 503, 504}

session = requests.Session()


def get(path: str, **params) -> dict:
    """GET with the key, pacing on OpenAQ's rate-limit headers (free tier: 60 a minute)."""
    if not OPENAQ_API_KEY:
        raise SystemExit("OPENAQ_API_KEY is empty: paste your key into .env")
    for attempt in range(8):
        try:
            r = session.get(f"{API}{path}", params=params, headers={"X-API-Key": OPENAQ_API_KEY}, timeout=120)
        except (requests.ConnectionError, requests.Timeout) as e:  # a dropped connection is retried, not fatal
            print(f"    network error ({type(e).__name__}), retrying in 30 s")
            time.sleep(30)
            continue
        reset = int(r.headers.get("x-ratelimit-reset", 60)) + 1
        if r.status_code in RETRY_CODES:
            wait = reset if r.status_code == 429 else 15 * (attempt + 1)
            print(f"    HTTP {r.status_code}, waiting {wait} s")
            time.sleep(wait)
            continue
        r.raise_for_status()
        if int(r.headers.get("x-ratelimit-remaining", 10)) < 2:
            time.sleep(reset)  # minute budget used up: wait for the window to reset
        return r.json()
    raise RuntimeError(f"OpenAQ kept failing on {path}")


# ---------- stage 1: coverage ----------
def fetch_locations(city) -> list[dict]:
    path = RAW_DIR / f"locations_{city.slug}.json"
    if not path.exists():
        payload = get("/locations", coordinates=f"{city.lat},{city.lon}", radius=RADIUS_M, limit=PAGE)
        path.write_text(json.dumps(payload), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8"))["results"]


def sensor_table() -> pd.DataFrame:
    rows = []
    for city in CITIES.values():
        for loc in fetch_locations(city):
            for s in loc["sensors"]:
                if s["parameter"]["name"] not in PARAMETERS:
                    continue
                rows.append({
                    "city": city.slug,
                    "location_id": loc["id"],
                    "location": loc["name"],
                    "provider": (loc.get("provider") or {}).get("name"),
                    "owner": (loc.get("owner") or {}).get("name"),
                    "is_monitor": loc.get("isMonitor"),  # True = reference-grade monitor
                    "is_mobile": loc.get("isMobile"),
                    "lat": loc["coordinates"]["latitude"],
                    "lon": loc["coordinates"]["longitude"],
                    "distance_km": round((loc.get("distance") or 0) / 1000, 1),
                    "sensor_id": s["id"],
                    "parameter": s["parameter"]["name"],
                    "units": s["parameter"]["units"],
                    "first_utc": (loc.get("datetimeFirst") or {}).get("utc"),
                    "last_utc": (loc.get("datetimeLast") or {}).get("utc"),
                })
    df = pd.DataFrame(rows)
    for col in ("first_utc", "last_utc"):
        df[col] = pd.to_datetime(df[col], utc=True)
    start, end = pd.Timestamp(START_DATE, tz="UTC"), pd.Timestamp(END_DATE, tz="UTC") + pd.Timedelta(days=1)
    overlap = (df.last_utc.clip(upper=end) - df.first_utc.clip(lower=start)).dt.days
    df["days_in_period"] = overlap.clip(lower=0).fillna(0).astype(int)
    return df.sort_values(["city", "parameter", "days_in_period"], ascending=[True, True, False])


def coverage() -> pd.DataFrame:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    df = sensor_table()
    df.to_csv(SENSORS_CSV, index=False)
    pm = df[(df.parameter == "pm25") & (df.days_in_period > 0)]
    print(f"\n{len(df)} sensors near the 5 cities; {len(pm)} PM2.5 sensors overlap the study period\n")
    print(pm.groupby("city").agg(sensors=("sensor_id", "size"), reference=("is_monitor", "sum"),
                                 longest_days=("days_in_period", "max"), total_days=("days_in_period", "sum")))
    print(f"\nSaved {SENSORS_CSV.relative_to(ROOT)}")
    return df


# ---------- stage 2: hourly values ----------
def download_sensor(sensor_id: int, first_utc: pd.Timestamp, last_utc: pd.Timestamp) -> Path:
    """Fetch one month per request. A month (<= 744 hours) fits on one page; deep paging is slow
    (page 5 of a year takes ~12 s against ~3.4 s for a month) and over six years it times out."""
    path = HOURS_DIR / f"sensor_{sensor_id}.json"
    if path.exists():
        return path
    start = max(pd.Timestamp(START_DATE, tz="UTC"), first_utc.floor("D"))
    end = min(pd.Timestamp(f"{END_DATE} 23:59:59", tz="UTC"), last_utc)
    results = []
    for m_from in pd.date_range(start.replace(day=1), end, freq="MS"):
        m_to = min(end, m_from + pd.offsets.MonthEnd(1) + pd.Timedelta(hours=23, minutes=59, seconds=59))
        payload = get(f"/sensors/{sensor_id}/hours", limit=PAGE,
                      datetime_from=max(m_from, start).strftime("%Y-%m-%dT%H:%M:%SZ"),
                      datetime_to=m_to.strftime("%Y-%m-%dT%H:%M:%SZ"))
        results += payload["results"]
    path.write_text(json.dumps(results), encoding="utf-8")
    return path


def load_sensor(path: Path) -> pd.DataFrame:
    results = json.loads(path.read_text(encoding="utf-8"))
    if not results:
        return pd.DataFrame()
    return pd.DataFrame({
        "sensor_id": int(path.stem.split("_")[1]),
        "time_utc": pd.to_datetime([r["period"]["datetimeFrom"]["utc"] for r in results], utc=True),
        "value": [r["value"] for r in results],
        "observed_count": [(r.get("coverage") or {}).get("observedCount") for r in results],
        "percent_complete": [(r.get("coverage") or {}).get("percentComplete") for r in results],
    })


def pm25_sensors() -> pd.DataFrame:
    """PM2.5 sensors that overlap the study period, most valuable first:
    reference monitors, then the longest-running low-cost sensors."""
    s = pd.read_csv(SENSORS_CSV, parse_dates=["first_utc", "last_utc"])
    s = s[(s.parameter == "pm25") & (s.days_in_period > 0)].drop_duplicates("sensor_id")
    return s.sort_values(["is_monitor", "days_in_period"], ascending=False)


def hours(worker: int = 0, workers: int = 1) -> pd.DataFrame | None:
    """Each request takes 3-5 s, so one process uses only ~12 of the 60 requests a minute the key
    allows. `hours 0 4` ... `hours 3 4` split the sensors across four parallel workers."""
    HOURS_DIR.mkdir(parents=True, exist_ok=True)
    todo = pm25_sensors()
    for i, s in enumerate(todo.itertuples(), 1):
        if i % workers != worker:
            continue
        print(f"  [{i}/{len(todo)}] {s.city} sensor {s.sensor_id} ({s.location}, {s.days_in_period} days)")
        download_sensor(s.sensor_id, s.first_utc, s.last_utc)
    return build() if workers == 1 else None


def build() -> pd.DataFrame:
    """Combine every sensor file downloaded so far into one table."""
    todo = pm25_sensors()
    files = [HOURS_DIR / f"sensor_{sid}.json" for sid in todo.sensor_id]
    frames = [load_sensor(p) for p in files if p.exists()]
    df = pd.concat([f for f in frames if not f.empty], ignore_index=True)
    df = df.merge(todo[["sensor_id", "city", "location_id", "is_monitor"]], on="sensor_id", how="left")
    df.to_parquet(OUT, index=False)
    print(f"\n{len(df):,} hourly PM2.5 records from {df.sensor_id.nunique()} sensors")
    print(df.groupby("city").agg(records=("value", "size"), sensors=("sensor_id", "nunique"),
                                 first=("time_utc", "min"), last=("time_utc", "max")))
    print(f"\nSaved {OUT.relative_to(ROOT)}")
    return df


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "coverage"
    args = [int(a) for a in sys.argv[2:]]
    {"coverage": coverage, "hours": hours, "build": build}[stage](*args)
