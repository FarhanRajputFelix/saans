"""Feature engineering as reusable functions: the same maths as notebook 04, for the live forecast.

Notebook 04 builds the training features step by step, with explanations. The live forecast must
compute exactly the same numbers from freshly downloaded data, so this module repeats that logic,
and notebook 07 checks that both give identical results on historical data (the parity check).

Input: one hourly frame per city with columns `time_utc`, `pm25`, `fires_300km` and the 13 weather
variables; the cleaned fire detections; and the saved settings in data/processed/feature_groups.json.
"""
import json

import numpy as np
import pandas as pd

from saans.config import CITIES, LOCAL_TZ, PROCESSED

SETTINGS = json.loads((PROCESSED / "feature_groups.json").read_text())
GROUPS = SETTINGS["groups"]
FEATURES = sum(GROUPS.values(), [])
GROUP_OF = {f: g for g, fs in GROUPS.items() for f in fs}
L_KM = SETTINGS["ufi_L_km"]


def dist_km(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    x = np.sin(lon2 - lon1) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(lon2 - lon1)
    return (np.degrees(np.arctan2(x, y)) + 360) % 360


def ufi(city: str, hourly: pd.DataFrame, fires: pd.DataFrame, window: tuple[int, int]) -> np.ndarray:
    """Upwind Fire Exposure Index: sum of FRP * exp(-d/L) * max(0, cos theta) over fires seen in the window."""
    c = CITIES[city]
    d = dist_km(c.lat, c.lon, fires.latitude.to_numpy(), fires.longitude.to_numpy())
    f = fires[d <= 600].assign(d_km=d[d <= 600])
    f = f.assign(bearing=bearing_deg(c.lat, c.lon, f.latitude.to_numpy(), f.longitude.to_numpy()))
    wind = hourly[["time_utc", "wind_direction_100m"]].rename(columns={"time_utc": "hour_utc"})
    f = f.merge(wind, on="hour_utc", how="left")
    upwind = np.clip(np.cos(np.radians(f.bearing - f.wind_direction_100m)), 0, None).fillna(0)
    weight = (f.frp * np.exp(-f.d_km / L_KM) * upwind).groupby(f.hour_utc).sum()
    s = weight.reindex(hourly.time_utc.to_numpy(), fill_value=0.0)
    lo, hi = window
    return s.rolling(hi - lo + 1, min_periods=1).sum().shift(lo).to_numpy()


def compute(city: str, hourly: pd.DataFrame, fires: pd.DataFrame, events: pd.DataFrame | None = None) -> pd.DataFrame:
    """All model features for every hour of one city's contiguous hourly frame."""
    m = hourly.sort_values("time_utc").reset_index(drop=True).copy()
    roll24 = lambda s, f="mean", minp=18: getattr(s.rolling(24, min_periods=minp), f)()

    # recent pollution
    m["pm25_24h"] = roll24(m.pm25)
    for h in [1, 3, 6, 24, 48]:
        m[f"pm25_lag{h}h"] = m.pm25.shift(h)
    m["pm25_now"] = m.pm25
    m["pm25_max24h"] = roll24(m.pm25, "max")
    m["pm25_trend24h"] = m.pm25_24h - m.pm25_24h.shift(24)

    # weather and stagnation
    for lvl in ["10m", "100m"]:
        ws, wd = m[f"wind_speed_{lvl}"], np.radians(m[f"wind_direction_{lvl}"])
        m[f"u_{lvl}"], m[f"v_{lvl}"] = -ws * np.sin(wd), -ws * np.cos(wd)
    m["dewpoint_depression"] = m.temperature_2m - m.dew_point_2m
    m["ventilation"] = m.boundary_layer_height * m.wind_speed_10m
    for new, col in [("ventilation_24h", "ventilation"), ("blh_24h", "boundary_layer_height"), ("rh_24h", "relative_humidity_2m"),
                     ("temp_24h", "temperature_2m"), ("wind_24h", "wind_speed_10m")]:
        m[new] = roll24(m[col], minp=12)
    m["rain_24h"] = roll24(m.precipitation, "sum", minp=12)
    m["pressure_change24h"] = m.surface_pressure - m.surface_pressure.shift(24)
    m["log_vent_24h"] = np.log1p(m.ventilation_24h)
    st = SETTINGS["stagnation_stats"]
    zs = [(st[c]["sign"] * m[c] - st[c]["mean"]) / st[c]["std"] for c in ["log_vent_24h", "rh_24h", "temp_24h"]]
    m["stagnation_index"] = sum(zs) / 3

    # upwind fires
    m["ufi_24_72h"] = ufi(city, m, fires, (24, 72))
    m["ufi_0_24h"] = ufi(city, m, fires, (0, 23))
    m["fires_300km_72h"] = m.fires_300km.rolling(72, min_periods=1).sum()

    # calendar and events (Pakistan time)
    local = m.time_utc.dt.tz_convert(LOCAL_TZ).dt.tz_localize(None)
    m["hour_pkt"], m["day_of_week"], m["month"] = local.dt.hour, local.dt.day_of_week, local.dt.month
    doy = local.dt.day_of_year
    m["doy_sin"], m["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    m["rice_burning_window"] = local.dt.month.isin([10, 11]).astype(int)
    m["wheat_burning_window"] = (((local.dt.month == 4) & (local.dt.day >= 15)) | (local.dt.month == 5)).astype(int)
    m["date"] = local.dt.floor("D")
    if events is not None:
        m = m.drop(columns=["measures_active", "crop_burning_ban_active", "fireworks_night"], errors="ignore")
        m = m.merge(events[events.city == city].drop(columns="city"), on="date", how="left")
    for col in ["measures_active", "crop_burning_ban_active", "fireworks_night"]:
        m[col] = m[col].fillna(0) if col in m else 0
    return m
