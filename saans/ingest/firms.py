"""Satellite fire detections from NASA FIRMS (free MAP_KEY in .env as FIRMS_MAP_KEY).

Two instruments (the proposal's VIIRS and MODIS):
    VIIRS_SNPP_SP    VIIRS on Suomi-NPP, 375 m pixels, passes ~01:30 and ~13:30 local time
    MODIS_SP         MODIS on Terra (~10:30) and Aqua (~13:30), 1 km pixels
VIIRS on NOAA-20 was tried too, but the server returned it ~3x slower (an estimated 5 hours),
so it was dropped; a partial year would have biased the fire features toward 2020.
"_SP" is the standard (science-quality) archive. The area API returns at most 5 days per call,
so each month is fetched in 5-day chunks and saved as one CSV.

The box covers Pakistani Punjab, Indian Punjab and Haryana (the crop-burning belt upwind of
Lahore in Oct-Nov) and northern Sindh down to Karachi.

Run from the repo root:
    python -m saans.ingest.firms

Writes:
    data/raw/firms/<source>/<yyyy-mm>.csv   untouched API output, one file per month
    data/interim/firms_fires.parquet        all detections in one table, UTC
"""
import io
import sys
import time
from datetime import date, timedelta

import pandas as pd
import requests

from saans.config import END_DATE, FIRMS_MAP_KEY, INTERIM, RAW, ROOT, START_DATE

API = "https://firms.modaps.eosdis.nasa.gov/api"
SOURCES = ["VIIRS_SNPP_SP", "MODIS_SP"]
BBOX = (66.0, 24.0, 78.0, 34.0)  # west, south, east, north
RAW_DIR = RAW / "firms"
OUT = INTERIM / "firms_fires.parquet"
PAUSE_S = 0.5


def key() -> str:
    if not FIRMS_MAP_KEY:
        raise SystemExit("FIRMS_MAP_KEY is empty: paste your key into .env")
    return FIRMS_MAP_KEY


def availability() -> pd.DataFrame:
    """First and last date each source can serve (the SP archive lags real time by a few months)."""
    r = requests.get(f"{API}/data_availability/csv/{key()}/all", timeout=60)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


def fetch_chunk(source: str, start: date, days: int) -> str:
    area = ",".join(str(v) for v in BBOX)
    url = f"{API}/area/csv/{key()}/{source}/{area}/{days}/{start.isoformat()}"
    for attempt in range(8):
        r = requests.get(url, timeout=180)
        time.sleep(PAUSE_S)
        text = r.text
        if r.status_code == 200 and (text.startswith("latitude") or not text.strip()):
            return text  # a CSV, possibly just the header when there were no fires
        # FIRMS reports errors as plain text with HTTP 200. Over the 5,000-per-10-minutes quota it
        # answers "Invalid MAP_KEY" (observed on 2026-10-24 at 4,886/5,000), so wait for the window.
        print(f"    {source} {start}: HTTP {r.status_code} {text[:100]!r}, waiting 120 s")
        time.sleep(120)
    raise RuntimeError(f"FIRMS kept failing on {source} {start} (key valid? quota?)")


def months(start: str, end: str):
    first = date.fromisoformat(start).replace(day=1)
    last = date.fromisoformat(end)
    while first <= last:
        nxt = (first + timedelta(days=32)).replace(day=1)
        yield first, min(nxt - timedelta(days=1), last)
        first = nxt


def download_month(source: str, first: date, last: date) -> None:
    path = RAW_DIR / source / f"{first:%Y-%m}.csv"
    if path.exists():
        return
    parts, day = [], first
    while day <= last:
        days = min(5, (last - day).days + 1)
        text = fetch_chunk(source, day, days)
        if text.strip():
            parts.append(pd.read_csv(io.StringIO(text)))
        day += timedelta(days=days)
    df = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def build_table() -> pd.DataFrame:
    frames = []
    for source in SOURCES:
        for path in sorted((RAW_DIR / source).glob("*.csv")):
            if path.stat().st_size < 10:  # a month with no fires
                continue
            df = pd.read_csv(path)
            df["source"] = source
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    # acq_time is an HHMM integer in UTC: 845 means 08:45
    hhmm = df.acq_time.astype(int).astype(str).str.zfill(4)
    df["time_utc"] = pd.to_datetime(df.acq_date + " " + hhmm, format="%Y-%m-%d %H%M", utc=True)
    df["confidence"] = df.confidence.astype(str)  # VIIRS uses l/n/h, MODIS uses 0-100
    return df.sort_values("time_utc").reset_index(drop=True)


def main(args: list[str]) -> None:
    """Download the given sources (all by default), then rebuild the combined table.
    `python -m saans.ingest.firms MODIS_SP` fetches one source, so sources can run in parallel;
    adding `--reverse` walks the months backwards, so a second worker can start from the end;
    `python -m saans.ingest.firms build` only rebuilds the table from files already on disk."""
    INTERIM.mkdir(parents=True, exist_ok=True)
    reverse = "--reverse" in args
    sources = [a for a in args if a != "--reverse"]
    if sources != ["build"]:
        for source in sources or SOURCES:
            month_list = list(months(START_DATE, END_DATE))
            for first, last in reversed(month_list) if reverse else month_list:
                print(f"  {source} {first:%Y-%m}")
                download_month(source, first, last)
        if sources:
            return  # one source of a parallel run: build once at the end with `build`
    df = build_table()
    df.to_parquet(OUT, index=False)
    print(f"\n{len(df):,} fire detections")
    print(df.groupby("source").agg(detections=("frp", "size"), first=("time_utc", "min"), last=("time_utc", "max")))
    print(f"\nSaved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main(sys.argv[1:])
