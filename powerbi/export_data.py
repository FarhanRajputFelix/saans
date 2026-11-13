"""Export everything the Power BI dashboard shows into flat CSV tables (powerbi/data/).

The Power BI report reads these files from GitHub, so it never runs Python or a model: like the Streamlit
dashboard, it shows precomputed forecasts for the two test seasons and the latest live snapshot. The scheduled
GitHub job re-runs this script after each live forecast, so a Refresh in Power BI picks up the new one.

Run from the repository root:  python powerbi/export_data.py
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from saans.aqi import BREAKPOINTS, CATEGORY_COLORS, SHORT_NAMES, category, pm25_to_aqi  # noqa: E402
from saans.config import CITIES  # noqa: E402
from saans.viz import DRIVER_COLORS  # noqa: E402

APP = ROOT / "app" / "data"
SNAP = APP / "live_snapshot"
REPORTS = ROOT / "reports"
OUT = Path(__file__).parent / "data"
TZ = "Asia/Karachi"
GROUPS = ["Recent pollution", "Weather", "Upwind fires", "Calendar"]
WHATIF = list(range(0, 101, 10))
UNSEEN = {"faisalabad", "multan"}  # no training data from either city
# dark-on-light text where the EPA colour is pale, so every tile stays readable
TEXT_ON = {"Good": "#0b0e14", "Moderate": "#0b0e14", "Unhealthy for Sensitive Groups": "#0b0e14",
           "Unhealthy": "#ffffff", "Very Unhealthy": "#ffffff", "Hazardous": "#ffffff"}


def cat_name(v):
    return category(v) if pd.notna(v) else None


def add_aqi(df, value, prefix):
    """AQI number, EPA category and its colour for a 24-hour mean column."""
    df[f"{prefix}aqi"] = pm25_to_aqi(df[value].to_numpy())
    df[f"{prefix}category"] = df[value].map(cat_name)
    df[f"{prefix}category_color"] = df[f"{prefix}category"].map(CATEGORY_COLORS)
    return df


def drivers_text(js):
    return "; ".join(f"{d['label']} ({d['ug_m3']:+.0f} µg/m³)" for d in json.loads(js)) if isinstance(js, str) else ""


def forecasts_table():
    """One row per forecast: replay rows (daily 08:00 issues, both test seasons) and the live snapshot rows."""
    rep = pd.read_parquet(APP / "forecasts_daily.parquet")
    rep["mode"] = "Replay"
    rep["season"] = rep.season.str.replace(" season", "", regex=False)
    live = pd.read_parquet(SNAP / "forecasts.parquet")
    live["mode"], live["season"] = "Live", "Live"
    df = pd.concat([rep, live], ignore_index=True)
    df["date"] = df.time_pkt.dt.tz_convert(TZ).dt.strftime("%Y-%m-%d")
    df["issued_pkt"] = df.time_pkt.dt.tz_convert(TZ).dt.strftime("%Y-%m-%d %H:%M")
    df["issue_key"] = df["mode"] + "|" + df["date"]
    df["forecast_id"] = df["issue_key"] + "|" + df.city
    df = add_aqi(df, "forecast_24h", "")
    df = add_aqi(df, "forecast_48h", "f48_")
    df = add_aqi(df, "target_24h", "observed_")
    df["category_text_color"] = df.category.map(TEXT_ON)
    df["category_short"] = df.category.map(lambda c: SHORT_NAMES.get(c, c))
    df["top_drivers"] = df.top_drivers.map(drivers_text)
    df["error_24h"] = df.forecast_24h - df.target_24h

    adv = json.loads((APP / "advisories.json").read_text(encoding="utf-8"))
    p = SNAP / "advisories.json"
    live_adv = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    key = df.city + "|" + df.date
    pick = lambda k, field, src: (src.get(k) or {}).get(field, "")
    for field, col in [("en", "advisory_english"), ("ur", "advisory_urdu"), ("source", "advisory_source")]:
        df[col] = [pick(k, field, live_adv if m == "Live" else adv) for k, m in zip(key, df["mode"])]
    df["advisory_source"] = df.advisory_source.map(lambda s: "AI Smog Explainer (LLM, numbers checked)" if s.startswith(("gemini", "groq"))
                                                   else "Rule-based template" if s else "")
    cols = ["forecast_id", "issue_key", "mode", "season", "city", "date", "issued_pkt", "pm25_24h", "forecast_24h", "q10", "q90",
            "aqi", "category", "category_short", "category_color", "category_text_color", "hazard_prob", "forecast_48h", "f48_aqi",
            "f48_category", "target_24h", "observed_aqi", "observed_category", "error_24h", "shap_base", "top_drivers",
            "advisory_english", "advisory_urdu", "advisory_source"]
    return df, df[cols].rename(columns={"pm25_24h": "last_24h", "shap_base": "typical_level", "target_24h": "observed_next_24h"})


def issues_table(df):
    iss = df.groupby("issue_key", as_index=False).agg(mode=("mode", "first"), season=("season", "first"),
                                                      date=("date", "first"), issued_pkt=("issued_pkt", "first"))
    return iss.sort_values(["mode", "date"])


def drivers_table(df):
    d = df.melt(id_vars="forecast_id", value_vars=[f"shap_{g}" for g in GROUPS], var_name="driver_group", value_name="ug_m3")
    d["driver_group"] = d.driver_group.str.removeprefix("shap_")
    d["group_order"] = d.driver_group.map({g: i for i, g in enumerate(GROUPS)})
    d["group_color"] = d.driver_group.map(DRIVER_COLORS)
    return d


def whatif_table(df):
    w = df.melt(id_vars="forecast_id", value_vars=[f"whatif_{p}" for p in WHATIF], var_name="fire_reduction_pct", value_name="forecast_ug_m3")
    w["fire_reduction_pct"] = w.fire_reduction_pct.str.removeprefix("whatif_").astype(int)
    return add_aqi(w, "forecast_ug_m3", "")


def chart_table(df):
    """Hourly series behind the 48-hour chart: 96 h of observations before each issue, the forecast for the next
    48 h (flat at the 24-hour means, as in the web dashboard), its 80% band, and for replays what actually happened."""
    obs = {"Replay": pd.read_parquet(APP / "observed_hourly.parquet"), "Live": pd.read_parquet(SNAP / "observed.parquet")}
    rows = []
    for mode, o in obs.items():
        o = o.dropna(subset=["pm25"])
        for city, oc in o.groupby("city"):
            s = oc.set_index("time_utc").pm25.sort_index()
            for r in df[(df["mode"] == mode) & (df.city == city)].itertuples():
                hours = pd.date_range(r.time_utc - pd.Timedelta(hours=96), r.time_utc + pd.Timedelta(hours=48), freq="h")
                ahead = (hours - r.time_utc) / pd.Timedelta(hours=1)
                val = s.reindex(hours)
                c = pd.DataFrame({"forecast_id": r.forecast_id, "hours_from_issue": ahead.astype(int),
                                  "time_pkt": hours.tz_convert(TZ).strftime("%Y-%m-%d %H:%M"),
                                  "observed": np.where(ahead <= 0, val, np.nan),
                                  "actual_after": np.where(ahead > 0, val, np.nan) if mode == "Replay" else np.nan})
                c["forecast"] = np.select([(ahead > 0) & (ahead <= 24), ahead > 24], [r.forecast_24h, r.forecast_48h], np.nan)
                c.loc[ahead == 0, "forecast"] = r.pm25_24h  # joins the forecast line to the last observation
                in_band = (ahead > 0) & (ahead <= 24)
                c["band_low"], c["band_high"] = np.where(in_band, r.q10, np.nan), np.where(in_band, r.q90, np.nan)
                rows.append(c)
    return pd.concat(rows, ignore_index=True).round(1)


def map_table(df):
    """Points for the map of each issue: the five cities (sized by forecast) and the fires seen in the 72 hours before."""
    cities = pd.DataFrame([{"city": k, "latitude": v.lat, "longitude": v.lon} for k, v in CITIES.items()])
    pts = df.merge(cities, on="city")[["issue_key", "city", "latitude", "longitude", "forecast_24h", "category"]]
    pts = pts.assign(kind="City", label=pts.city.str.title() + " " + pts.forecast_24h.round(0).astype(int).astype(str) + " µg/m³",
                     size=pts.forecast_24h, legend=pts.category, detections=np.nan)
    fires = []
    issue_times = df.groupby("issue_key").time_utc.first()
    hist = pd.read_parquet(ROOT / "data" / "processed" / "fires_clean.parquet", columns=["latitude", "longitude", "frp", "hour_utc"])
    live_f = pd.read_parquet(SNAP / "fires.parquet")
    for key, t in issue_times.items():
        src = live_f if key.startswith("Live") else hist
        f = src[(src.hour_utc > t - pd.Timedelta(hours=72)) & (src.hour_utc <= t)
                & src.latitude.between(23, 36) & src.longitude.between(66, 79)]
        if f.empty:
            continue
        g = f.assign(latitude=f.latitude.round(1), longitude=f.longitude.round(1)).groupby(["latitude", "longitude"]).size()
        fires.append(g.rename("detections").reset_index().assign(issue_key=key))
    fires = pd.concat(fires, ignore_index=True) if fires else pd.DataFrame(columns=["latitude", "longitude", "detections", "issue_key"])
    fires = fires.assign(kind="Fire", city="", label="Fire detections",
                         size=1.0, legend="Fire detections, last 72 h", forecast_24h=np.nan, category="")
    cols = ["issue_key", "kind", "city", "label", "latitude", "longitude", "size", "legend", "detections"]
    return pd.concat([pts[cols], fires[cols]], ignore_index=True)


def markdown_tables(path):
    """Every table in a generated markdown report, keyed by the heading above it."""
    tables, heading, block = {}, None, []
    for line in path.read_text(encoding="utf-8").splitlines() + [""]:
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
        elif line.startswith("|"):
            block.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif block:
            head, body = block[0], [r for r in block[2:]]
            tables[heading] = pd.DataFrame(body, columns=head)
            block = []
    return tables


def number(s):
    s = s.astype(str).str.replace(",", "", regex=False).str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(s, errors="coerce")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    full, fc = forecasts_table()
    tables = {
        "forecasts": fc,
        "issues": issues_table(full),
        "drivers": drivers_table(full),
        "whatif": whatif_table(full),
        "chart_hourly": chart_table(full),
        "map_points": map_table(full),
        "cities": pd.DataFrame([{"city": k, "City": v.name, "latitude": v.lat, "longitude": v.lon,
                                 "in_training": "No (unseen city)" if k in UNSEEN else "Yes"} for k, v in CITIES.items()]),
        "categories": pd.DataFrame([{"category": c, "category_short": SHORT_NAMES.get(c, c), "category_order": i,
                                     "pm25_range": f"{lo:g}-{hi:g}" if i < 5 else f"{lo:g}+", "aqi_range": f"{a}-{b}" if i < 5 else "301+",
                                     "color": CATEGORY_COLORS[c], "text_color": TEXT_ON[c]}
                                    for i, (lo, hi, a, b, c) in enumerate(BREAKPOINTS)]),
    }
    # model evaluation
    ev = pd.read_csv(REPORTS / "evaluation_regression.csv")
    ev["season"] = ev.season.str.replace(" season", "", regex=False)
    tables["evaluation_regression"] = ev
    cl = pd.read_csv(REPORTS / "evaluation_classifier.csv")
    cl["season"] = cl.season.str.replace(" season", "", regex=False)
    tables["evaluation_classifier"] = cl
    ab = pd.read_csv(REPORTS / "ablation_fire_features.csv")
    ab["season"] = ab.season.str.replace(" season", "", regex=False)
    tables["ablation_fire_features"] = ab
    sh = pd.read_csv(REPORTS / "shap_group_shares.csv", index_col=0).rename_axis("driver_group").reset_index()
    tables["shap_group_shares"] = sh.melt(id_vars="driver_group", var_name="share_of", value_name="percent").assign(
        share_of=lambda d: d.share_of.map({"share_of_whole_forecast_%": "Whole forecast", "share_of_predicted_change_%": "Predicted change"}))
    # data quality (parsed from the generated Data Quality Report, so the numbers are the notebook's own)
    md = markdown_tables(REPORTS / "data_quality_report.md")
    tot = md["Totals: received vs kept"]
    for c in ["received", "after_cleaning", "share_kept"]:
        tot[c] = number(tot[c])
    tables["dq_totals"] = tot
    steps = md["Every cleaning action, in order"]
    for c in ["step", "rows_before", "rows_after", "removed"]:
        steps[c] = number(steps[c])
    tables["dq_cleaning_steps"] = steps.reset_index(names="order")
    sens = md["Sensors received, kept and rejected"]
    for c in sens.columns[1:]:
        sens[c] = number(sens[c])
    tables["dq_sensors"] = sens
    tables["dq_raw_records"] = pd.read_csv(REPORTS / "raw_record_counts.csv")
    s = pd.read_csv(ROOT / "data" / "interim" / "openaq_sensors.csv")
    s = s[(s.parameter == "pm25") & (s.days_in_period > 0)].drop_duplicates("sensor_id")
    s["type"] = np.where(s.is_monitor, "Reference monitor", "Low-cost sensor")
    tables["dq_sensor_map"] = s[["city", "provider", "type", "location", "lat", "lon", "first_utc", "last_utc", "days_in_period"]]
    # live run status
    st = json.loads((SNAP / "status.json").read_text())
    tables["live_status"] = pd.DataFrame([{"city": c, **{k: v for k, v in d.items() if k != "issued_at_utc"}} for c, d in st["cities"].items()]).assign(
        run_pkt=pd.Timestamp(st["run_utc"]).tz_convert(TZ).strftime("%Y-%m-%d %H:%M"),
        fire_data="fresh NASA FIRMS data" if st["fires"]["fresh"] else "no fresh fire data in this run",
        fire_detections=st["fires"]["detections"])
    # the cleaned hourly table is read by Power BI straight from data/processed/csv (one CSV per city)

    for name, t in tables.items():
        t.to_csv(OUT / f"{name}.csv", index=False, encoding="utf-8")
        print(f"{name:24s} {len(t):>8,} rows  {(OUT / f'{name}.csv').stat().st_size / 1e6:6.2f} MB")


if __name__ == "__main__":
    main()
