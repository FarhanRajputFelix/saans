"""Smog news headlines from the GDELT DOC 2.0 API (free, no key).

GDELT indexes online news worldwide. For every half-month of every smog season (October to
January) we pull up to 250 Pakistani articles that mention smog or AQI in the study cities.
Only the headline, outlet, link and date are kept; the LLM turns them into structured events
(school closures, traffic bans, smog emergencies, fireworks nights) in notebook 05.

Run from the repo root:
    python -m saans.ingest.news

Writes:
    data/raw/gdelt/<yyyy-mm-dd>.json        untouched API response per half-month window
    data/interim/news_headlines.csv         de-duplicated headlines, one row each
"""
import json
import time
from datetime import date, timedelta

import pandas as pd
import requests

from saans.config import END_DATE, INTERIM, RAW, ROOT, START_DATE

API = "https://api.gdeltproject.org/api/v2/doc/doc"
QUERY = "(smog OR AQI) (Lahore OR Punjab OR Multan OR Faisalabad OR Islamabad OR Karachi) sourcecountry:pakistan"
SEASON_MONTHS = {10, 11, 12, 1}
RAW_DIR = RAW / "gdelt"
OUT = INTERIM / "news_headlines.csv"
PAUSE_S = 10  # GDELT allows roughly one request every 5 seconds per IP


def windows(start: str, end: str):
    """Half-month windows (1st-15th, 16th-end) inside the smog-season months."""
    day, last = date.fromisoformat(start).replace(day=1), date.fromisoformat(end)
    while day <= last:
        month_end = (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        if day.month in SEASON_MONTHS:
            yield day, day.replace(day=15)
            yield day.replace(day=16), month_end
        day = month_end + timedelta(days=1)


def fetch(first: date, last: date) -> list[dict]:
    path = RAW_DIR / f"{first.isoformat()}.json"
    if not path.exists():
        params = {"query": QUERY, "mode": "artlist", "maxrecords": 250, "format": "json",
                  "startdatetime": f"{first:%Y%m%d}000000", "enddatetime": f"{last:%Y%m%d}235959"}
        for attempt in range(8):
            time.sleep(PAUSE_S)
            r = requests.get(API, params=params, timeout=90, headers={"User-Agent": "saans-student-project"})
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            break
        else:
            raise RuntimeError(f"GDELT kept rate-limiting {first}")
        # GDELT answers an empty window with an empty body instead of {"articles": []}
        payload = r.json() if r.text.strip().startswith("{") else {"articles": []}
        path.write_text(json.dumps(payload), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8")).get("articles", [])


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    rows = []
    for first, last in windows(START_DATE, END_DATE):
        arts = fetch(first, last)
        print(f"  {first} to {last}: {len(arts)} articles")
        rows += arts
    df = pd.DataFrame(rows)[["seendate", "domain", "title", "url", "language"]]
    df["time_utc"] = pd.to_datetime(df.seendate, format="%Y%m%dT%H%M%SZ", utc=True)
    raw_n = len(df)
    df["title_key"] = df.title.str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.split().str.join(" ")
    df = df.drop_duplicates("url").drop_duplicates("title_key").sort_values("time_utc")
    df.drop(columns=["seendate", "title_key"]).to_csv(OUT, index=False)
    print(f"\n{raw_n:,} articles received, {len(df):,} after removing duplicate links and headlines")
    print(f"Saved {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
