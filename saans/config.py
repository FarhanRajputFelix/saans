"""Settings shared by every SAANS module: cities, study period, folders and API keys.

Change things here, never by editing numbers buried inside other scripts.
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")  # API keys live in .env, which git ignores

# ---------- folders: raw is never edited, interim is parsed, processed is model-ready ----------
DATA = ROOT / "data"
RAW = DATA / "raw"
INTERIM = DATA / "interim"
PROCESSED = DATA / "processed"
REPORTS = ROOT / "reports"

# ---------- study period ----------
# The 2020-2023 smog seasons train the models; the 2024 and 2025 seasons are held out for testing.
# A season runs October to January, so the 2025 season ends on 31 Jan 2026.
START_DATE = "2020-01-01"
END_DATE = "2026-01-31"
LOCAL_TZ = "Asia/Karachi"  # PKT = UTC+5, no daylight saving


@dataclass(frozen=True)
class City:
    slug: str
    name: str
    lat: float
    lon: float


CITIES = {c.slug: c for c in [
    City("lahore", "Lahore", 31.5497, 74.3436),
    City("faisalabad", "Faisalabad", 31.4504, 73.1350),
    City("multan", "Multan", 30.1575, 71.5249),
    City("islamabad", "Islamabad", 33.6844, 73.0479),
    City("karachi", "Karachi", 24.8607, 67.0011),  # Sindh, coastal: a contrast city far from Punjab's fires
]}

# ---------- API keys (see .env.example) ----------
OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "")
FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "")
