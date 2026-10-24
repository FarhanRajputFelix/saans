"""Live smog forecast for today, from data fetched right now.

1. PM2.5: the last 4 days from every OpenAQ sensor still reporting near each city (up to 10 per city),
   cleaned with the rules of notebook 02 (nulls, negatives, >1,000, completeness, stuck runs, spikes,
   dropouts; humidity correction only for providers where notebook 02 showed it helps).
2. Weather: the last 4 days from the Open-Meteo forecast API (same 13 variables, incl. boundary layer height).
3. Fires: the last 4 days of NASA FIRMS near-real-time detections (VIIRS S-NPP + MODIS), cleaned as in
   notebook 02. Near-real-time data carries no `type`, so the static heat sources found in the archive are
   removed by location.
4. Features: saans.features.compute, the same maths as notebook 04 (checked in notebook 07).
5. Forecast and SHAP: the saved LightGBM models; SHAP values from LightGBM's built-in TreeSHAP.

Every step records what happened in `status`, so the dashboard can say which inputs were fresh.
Needs OPENAQ_API_KEY and FIRMS_MAP_KEY (Open-Meteo needs none).
"""
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor

import lightgbm as lgb
import numpy as np
import pandas as pd
import requests

from saans import config, features
from saans.aqi import risk_level
from saans.config import CITIES, PROCESSED, ROOT
from saans.ingest.firms import BBOX
from saans.ingest.weather import VARIABLES

DAYS = 4
MAX_SENSORS = 10
MODELS = ROOT / "models"
CARD = json.loads((MODELS / "model_card.json").read_text())
LABELS = json.loads((ROOT / "saans" / "feature_labels.json").read_text(encoding="utf-8"))
NO_CORRECTION = {"AirGradient", "Clarity"}  # notebook 02: the EPA correction made these providers worse
FIRE_COLS = features.GROUPS["Upwind fires"]
EMPTY_FIRES = pd.DataFrame({"latitude": [], "longitude": [], "frp": [], "hour_utc": pd.to_datetime([], utc=True)})


def _scrub(msg: str) -> str:
    """Remove API keys from error text (FIRMS puts its key in the URL)."""
    for k in (config.FIRMS_MAP_KEY, config.OPENAQ_API_KEY):
        if k:
            msg = msg.replace(k, "***")
    return msg


def _get(url, attempts=3, **kw):
    """GET with retries; a server that does not accept the connection within 10 s is given up on quickly."""
    for attempt in range(attempts):
        try:
            r = requests.get(url, timeout=(10, 60), **kw)
            if r.status_code == 429:
                time.sleep(min(int(r.headers.get("x-ratelimit-reset", 10)) + 1, 60))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException:
            time.sleep(3)
    return None


# ---------- inputs ----------
def fetch_weather(city: str, end: pd.Timestamp) -> pd.DataFrame:
    c = CITIES[city]
    r = _get("https://api.open-meteo.com/v1/forecast",
             params={"latitude": c.lat, "longitude": c.lon, "hourly": ",".join(VARIABLES), "timezone": "GMT",
                     "wind_speed_unit": "ms", "past_days": DAYS, "forecast_days": 1})
    if r is None:
        raise RuntimeError("Open-Meteo did not answer")
    df = pd.DataFrame(r.json()["hourly"])
    df["time_utc"] = pd.to_datetime(df.pop("time"), utc=True)
    return df[df.time_utc <= end].reset_index(drop=True)


def active_sensors(city: str, end: pd.Timestamp) -> pd.DataFrame:
    """PM2.5 sensors within 25 km that reported in the last 2 days, best first."""
    c = CITIES[city]
    r = _get("https://api.openaq.org/v3/locations", headers={"X-API-Key": config.OPENAQ_API_KEY},
             params={"coordinates": f"{c.lat},{c.lon}", "radius": 25_000, "limit": 1000})
    rows = []
    for loc in (r.json()["results"] if r is not None else []):
        last = pd.to_datetime((loc.get("datetimeLast") or {}).get("utc"), utc=True)
        for s in loc["sensors"]:
            if s["parameter"]["name"] == "pm25" and pd.notna(last) and last >= end - pd.Timedelta(days=2):
                rows.append({"sensor_id": s["id"], "location": loc["name"], "provider": (loc.get("provider") or {}).get("name"),
                             "is_monitor": bool(loc.get("isMonitor")), "last_utc": last})
    df = pd.DataFrame(rows)
    return df.sort_values(["is_monitor", "last_utc"], ascending=False).head(MAX_SENSORS) if len(df) else df


def fetch_pm25(city: str, start: pd.Timestamp, end: pd.Timestamp, wx: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    sensors = active_sensors(city, end)
    rows = []
    for s in sensors.itertuples():
        r = _get(f"https://api.openaq.org/v3/sensors/{s.sensor_id}/hours", headers={"X-API-Key": config.OPENAQ_API_KEY},
                 params={"datetime_from": start.strftime("%Y-%m-%dT%H:%M:%SZ"), "datetime_to": end.strftime("%Y-%m-%dT%H:%M:%SZ"), "limit": 1000})
        for x in (r.json()["results"] if r is not None else []):
            rows.append({"sensor_id": s.sensor_id, "provider": s.provider, "is_monitor": s.is_monitor,
                         "time_utc": x["period"]["datetimeFrom"]["utc"], "value": x["value"],
                         "observed_count": (x.get("coverage") or {}).get("observedCount")})
    info = {"sensors_reporting": int(len(sensors)), "sensor_hours_received": len(rows)}
    if not rows:
        return pd.DataFrame(columns=["time_utc", "pm25"]), info
    aq = pd.DataFrame(rows)
    aq["time_utc"] = pd.to_datetime(aq.time_utc, utc=True).dt.floor("h")
    aq = aq.drop_duplicates(["sensor_id", "time_utc"]).sort_values(["sensor_id", "time_utc"]).reset_index(drop=True)
    # the rules of notebook 02, steps 3 to 6 (no neighbour test: too few hours for stable neighbour medians)
    aq = aq[aq.value.notna() & (aq.value >= 1) & (aq.value <= 1000)]  # < 1 ug/m3 is a faulting sensor's zero
    typical = aq.groupby("sensor_id").observed_count.transform("median")
    aq = aq[aq.observed_count.isna() | (aq.observed_count >= 0.75 * typical)].reset_index(drop=True)
    g = aq.groupby("sensor_id")
    same = (aq.value == g.value.shift()) & (aq.time_utc - g.time_utc.shift() == pd.Timedelta("1h"))
    aq = aq[aq.groupby((~same).cumsum()).value.transform("size") < 6].reset_index(drop=True)
    g = aq.groupby("sensor_id")
    prev_v, next_v = g.value.shift(1), g.value.shift(-1)
    spike = (aq.value > 3 * prev_v) & (aq.value > 3 * next_v) & (aq.value - np.maximum(prev_v, next_v) > 150)
    drop = (aq.value < 0.25 * prev_v) & (aq.value < 0.25 * next_v) & (np.minimum(prev_v, next_v) > 60)
    aq = aq[~(spike | drop)]
    aq = aq.merge(wx[["time_utc", "relative_humidity_2m"]], on="time_utc", how="left")
    fix = ~aq.is_monitor & ~aq.provider.isin(NO_CORRECTION)
    aq.loc[fix, "value"] = (0.524 * aq.loc[fix, "value"] - 0.0862 * aq.loc[fix, "relative_humidity_2m"] + 5.75).clip(lower=0)
    ref = aq[aq.is_monitor].groupby("time_utc").value.mean()
    low = aq[~aq.is_monitor].groupby("time_utc").value.median()
    pm = ref.combine_first(low).rename("pm25").reset_index().sort_values("time_utc")
    prev_c, next_c = pm.pm25.shift(1), pm.pm25.shift(-1)  # second, city-level dropout pass (notebook 02, step 5)
    pm.loc[(pm.pm25 < 0.25 * prev_c) & (pm.pm25 < 0.25 * next_c) & (np.minimum(prev_c, next_c) > 60), "pm25"] = np.nan
    info["sensor_hours_kept"] = int(len(aq))
    return pm, info


def fetch_fires() -> tuple[pd.DataFrame, dict]:
    static = set(json.loads((PROCESSED / "static_fire_cells.json").read_text()))
    frames, ok, errors = [], [], []
    area = ",".join(str(v) for v in BBOX)
    for src in ["VIIRS_SNPP_NRT", "MODIS_NRT"]:
        r = _get(f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{config.FIRMS_MAP_KEY}/{src}/{area}/{DAYS}", attempts=2)
        if r is None or not r.text.startswith("latitude"):
            errors.append(f"{src}: no answer" if r is None else f"{src}: {_scrub(r.text[:80])}")
            continue
        df = pd.read_csv(io.StringIO(r.text))
        df["source"] = src
        frames.append(df)
        ok.append(src)
    if not frames:
        return EMPTY_FIRES, {"fresh": False, "sources": [], "errors": errors, "detections": 0}
    f = pd.concat(frames, ignore_index=True)
    raw = len(f)
    hhmm = f.acq_time.astype(int).astype(str).str.zfill(4)
    f["time_utc"] = pd.to_datetime(f.acq_date + " " + hhmm, format="%Y-%m-%d %H%M", utc=True)
    conf = f.confidence.astype(str)
    low = np.where(f.source.str.startswith("VIIRS"), conf == "l", pd.to_numeric(conf, errors="coerce") < 30)
    f = f[~low]
    f["cell"] = (f.latitude * 100).round().astype(int).astype(str) + "_" + (f.longitude * 100).round().astype(int).astype(str)
    f = f[~f.cell.isin(static)]
    f = (f.sort_values("frp", ascending=False).groupby(["cell", "acq_date", "daynight"], as_index=False)
         .agg(latitude=("latitude", "first"), longitude=("longitude", "first"), frp=("frp", "first"), time_utc=("time_utc", "min")))
    f["hour_utc"] = f.time_utc.dt.floor("h")
    return f, {"fresh": True, "sources": ok, "errors": errors, "detections_raw": raw, "detections": int(len(f))}


# ---------- forecast ----------
_BOOST = {}


def booster(name: str) -> lgb.Booster:
    if name not in _BOOST:
        _BOOST[name] = lgb.Booster(model_file=str(MODELS / f"{name}.txt"))
    return _BOOST[name]


def predict(rows: pd.DataFrame) -> pd.DataFrame:
    """Forecasts, band, hazard probability, grouped SHAP and the what-if curve, as in notebook 05."""
    X = rows[features.FEATURES].astype(float)
    level = rows.pm25_24h.to_numpy()
    out = rows[["city", "time_utc", "pm25_24h"]].copy()
    out["forecast_24h"] = level + booster("reg24_change").predict(X)
    out["forecast_48h"] = level + booster("reg48_change").predict(X)
    out["q10"] = level + booster("q10_change").predict(X)
    out["q90"] = level + booster("q90_change").predict(X)
    out["hazard_prob"] = booster("hazard").predict(X)
    contrib = booster("reg24_change").predict(X, pred_contrib=True)
    c = pd.DataFrame(contrib[:, :-1], columns=features.FEATURES, index=rows.index)
    c["pm25_24h"] += level - CARD["level_ref"]
    out["shap_base"] = CARD["level_ref"] + contrib[:, -1]
    for g, cols in features.GROUPS.items():
        out[f"shap_{g}"] = c[cols].sum(axis=1)
    out["top_drivers"] = [json.dumps([{"feature": f, "label": LABELS.get(f, f), "group": features.GROUP_OF[f], "ug_m3": round(float(v), 1)}
                                      for f, v in c.loc[i].sort_values(ascending=False).head(3).items()]) for i in rows.index]
    for r in np.arange(0, 1.01, 0.1):
        X2 = X.copy()
        X2[FIRE_COLS] *= (1 - r)
        out[f"whatif_{int(round(r * 100))}"] = level + booster("reg24_change").predict(X2)
    out["risk_level"] = [risk_level(v)[0] for v in out.forecast_24h]
    out["time_pkt"] = out.time_utc.dt.tz_convert("Asia/Karachi")
    return out


def _city_inputs(city: str, start: pd.Timestamp, end: pd.Timestamp):
    try:
        wx = fetch_weather(city, end)
        pm, info = fetch_pm25(city, start, end, wx)
        return wx, pm, info, None
    except Exception as e:
        return None, None, None, e


def forecast() -> dict:
    """Run the whole live pipeline. Returns forecasts (one row per city), observed hourly PM2.5 and status."""
    end = pd.Timestamp.now(tz="UTC").floor("h")
    start = end - pd.Timedelta(days=DAYS)
    status = {"run_utc": str(end), "cities": {}}
    with ThreadPoolExecutor(max_workers=6) as pool:  # fires and the five cities are fetched at the same time
        fire_job = pool.submit(fetch_fires)
        city_jobs = {city: pool.submit(_city_inputs, city, start, end) for city in CITIES}
        fires, status["fires"] = fire_job.result()
        inputs = {city: job.result() for city, job in city_jobs.items()}
    rows, observed = [], []
    for city, c in CITIES.items():
        try:
            wx, pm, info, err = inputs[city]
            if err is not None:
                raise err
            h = wx.merge(pm, on="time_utc", how="left")
            d = features.dist_km(c.lat, c.lon, fires.latitude.to_numpy(), fires.longitude.to_numpy())
            near = fires[d <= 300].groupby("hour_utc").size()
            h["fires_300km"] = near.reindex(h.time_utc.to_numpy(), fill_value=0).to_numpy()
            f = features.compute(city, h, fires).assign(city=city)
            usable = f[f.pm25_24h.notna()]
            info["hours_with_pm25_last_24h"] = int(h.pm25.tail(24).notna().sum())
            if usable.empty:
                info["result"] = "not enough PM2.5 in the last 24 hours to forecast"
            else:
                rows.append(usable.tail(1))
                info["result"] = "forecast issued"
                info["issued_at_utc"] = str(usable.time_utc.iloc[-1])
            observed.append(h[["time_utc", "pm25"]].dropna().assign(city=city))
        except Exception as e:  # one city failing must not stop the others
            info = {"result": f"failed: {_scrub(str(e))[:120]}"}
        status["cities"][city] = info
    fc = predict(pd.concat(rows, ignore_index=True)) if rows else pd.DataFrame()  # one row per city, unique index
    obs = pd.concat(observed, ignore_index=True) if observed else pd.DataFrame(columns=["time_utc", "pm25", "city"])
    return {"forecasts": fc, "observed": obs, "status": status}


def save_snapshot(result: dict, folder=ROOT / "app" / "data" / "live_snapshot") -> None:
    """Freeze one live run, so the dashboard can show it when no API keys are configured."""
    folder.mkdir(parents=True, exist_ok=True)
    result["forecasts"].to_parquet(folder / "forecasts.parquet", index=False)
    result["observed"].to_parquet(folder / "observed.parquet", index=False)
    (folder / "status.json").write_text(json.dumps(result["status"], indent=1, default=str))


def load_snapshot(folder=ROOT / "app" / "data" / "live_snapshot") -> dict | None:
    if not (folder / "forecasts.parquet").exists():
        return None
    return {"forecasts": pd.read_parquet(folder / "forecasts.parquet"), "observed": pd.read_parquet(folder / "observed.parquet"),
            "status": json.loads((folder / "status.json").read_text())}
