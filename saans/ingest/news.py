"""Smog news headlines from the GDELT DOC 2.0 API (free, no key).

GDELT indexes online news worldwide. For each half of every smog season (Oct-Nov, Dec-Jan)
we pull up to 250 Pakistani articles that mention smog or AQI in the study cities.
Only the headline, outlet, link and date are kept; the LLM turns them into structured events
(school closures, traffic bans, smog emergencies, fireworks nights) in notebook 05.

Run from the repo root:
    python -m saans.ingest.news

Writes:
    data/raw/gdelt/<yyyy-mm-dd>.json        untouched API response per window (named by first day)
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
RAW_DIR = RAW / "gdelt"
OUT = INTERIM / "news_headlines.csv"
PAUSE_S = 10  # GDELT allows roughly one request every 5 seconds per IP


def month_end(d: date) -> date:
    return (d.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def windows(start: str, end: str):
    """Two windows per smog season, Oct-Nov and Dec-Jan (GDELT returns at most 250 articles per
    request and throttles hard, so fewer, wider windows finish sooner). January 2020, the tail of
    the 2019 season, is its own window."""
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first.month == 1:
        yield first, month_end(first)
    for year in range(first.year, last.year):
        yield date(year, 10, 1), date(year, 11, 30)
        yield date(year, 12, 1), min(month_end(date(year + 1, 1, 1)), last)


def fetch(first: date, last: date) -> list[dict]:
    path = RAW_DIR / f"{first.isoformat()}.json"
    if not path.exists():
        params = {"query": QUERY, "mode": "artlist", "maxrecords": 250, "format": "json",
                  "startdatetime": f"{first:%Y%m%d}000000", "enddatetime": f"{last:%Y%m%d}235959"}
        for attempt in range(12):
            time.sleep(PAUSE_S)
            try:
                r = requests.get(API, params=params, timeout=90, headers={"User-Agent": "saans-student-project"})
            except (requests.ConnectionError, requests.Timeout):
                print("    network error, retrying in 30 s")
                time.sleep(30)
                continue
            if r.status_code == 429:
                print("    rate limited, waiting 30 s")
                time.sleep(30)
                continue
            r.raise_for_status()
            break
        else:
            raise RuntimeError(f"GDELT kept rate-limiting {first}")
        # GDELT answers an empty window with an empty body instead of {"articles": []}
        payload = r.json() if r.text.strip().startswith("{") else {"articles": []}
        path.write_text(json.dumps(payload), encoding="utf-8")
    return json.loads(path.read_text(encoding="utf-8")).get("articles", [])


def main(fetch_missing: bool = True) -> None:
    """Fetch every window (skipping saved ones), then build the headline table.
    `python -m saans.ingest.news build` builds from the windows already saved, fetching nothing."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)
    rows = []
    for first, last in windows(START_DATE, END_DATE):
        if not fetch_missing and not (RAW_DIR / f"{first.isoformat()}.json").exists():
            continue
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
    import sys
    main(fetch_missing=sys.argv[1:] != ["build"])
