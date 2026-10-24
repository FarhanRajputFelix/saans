"""SAANS dashboard: today's smog forecast for five Pakistani cities, the reasons, and the data behind it.

Tabs
- Live forecast: issued from data fetched right now (needs OPENAQ_API_KEY and FIRMS_MAP_KEY in the app's
  secrets; GEMINI_API_KEY or GROQ_API_KEY for the LLM advisory). Without keys it shows the latest
  committed snapshot, clearly dated.
- Replay: the two held-out test seasons day by day, with what actually happened.
- Cleaned data: the hourly master table, filterable and downloadable.
- Data quality, Model performance, About.

Local run:  streamlit run app/streamlit_app.py
"""
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="SAANS smog forecast", page_icon="🌫️", layout="wide")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
KEY_NAMES = ["OPENAQ_API_KEY", "FIRMS_MAP_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"]


def secret(name: str) -> str:
    """A key from Streamlit secrets, at the top level or inside any [section]; '' if absent."""
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
        for section in st.secrets.values():
            if hasattr(section, "keys") and name in section:
                return str(section[name]).strip()
    except Exception:
        pass  # no secrets file at all (local run uses .env instead)
    return ""


for _k in KEY_NAMES:  # Streamlit Cloud secrets -> environment, on every run (keys can be added while the app is up)
    if secret(_k):
        os.environ[_k] = secret(_k)

from saans import advisory, config  # noqa: E402
from saans.aqi import HAZARDOUS_PM25, pm25_to_aqi, risk_level  # noqa: E402

# saans.config read the keys when the process first started; refresh its copies so keys added later take effect
config.OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "") or config.OPENAQ_API_KEY
config.FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "") or config.FIRMS_MAP_KEY

DATA = ROOT / "app" / "data"
REPORTS = ROOT / "reports"
PROCESSED = ROOT / "data" / "processed"
CITIES = {"lahore": ("Lahore", 31.5497, 74.3436), "faisalabad": ("Faisalabad", 31.4504, 73.1350),
          "multan": ("Multan", 30.1575, 71.5249), "islamabad": ("Islamabad", 33.6844, 73.0479),
          "karachi": ("Karachi", 24.8607, 67.0011)}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
RISK_ROLE = {"Green": "good", "Yellow": "warning", "Orange": "serious", "Red": "critical"}
RISK_ICON = {"Green": "●", "Yellow": "▲", "Orange": "◆", "Red": "■"}
RISK_SYMBOL = {"Green": "circle", "Yellow": "triangle-up", "Orange": "diamond", "Red": "square"}  # shape, not colour alone
DRIVERS = {"Recent pollution": "#2a78d6", "Weather": "#eb6834", "Upwind fires": "#1baf7a", "Calendar": "#eda100"}
INK, INK_2, MUTED, GRID, SURFACE = "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#fcfcfb"
HAVE_KEYS = bool(config.OPENAQ_API_KEY)
HAVE_LLM = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY"))


# ---------------- data ----------------
@st.cache_data
def load_replay():
    daily = pd.read_parquet(DATA / "forecasts_daily.parquet")
    daily["date"] = daily.time_pkt.dt.tz_convert("Asia/Karachi").dt.date
    hourly = pd.read_parquet(DATA / "observed_hourly.parquet")
    p = DATA / "advisories.json"
    adv = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return daily, hourly, adv, json.loads((DATA / "evaluation.json").read_text())


@st.cache_data
def load_master():
    return pd.read_parquet(PROCESSED / "master_hourly.parquet")


@st.cache_data(ttl=3600, show_spinner=False)
def run_live(hour_key: str):
    """One live run per hour at most (hour_key changes every hour)."""
    from saans import live
    res = live.forecast()
    res["advisories"] = {}
    for r in res["forecasts"].itertuples():
        d = r.time_pkt.strftime("%Y-%m-%d")
        res["advisories"][f"{r.city}|{d}"] = advisory.write(r.city, d, r.forecast_24h, r.hazard_prob, r.top_drivers, use_llm=HAVE_LLM)
    return res


def load_snapshot():
    from saans import live
    snap = live.load_snapshot()
    if snap is not None:
        p = DATA / "live_snapshot" / "advisories.json"
        snap["advisories"] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return snap


# ---------------- shared forecast view ----------------
def badge(level: str) -> str:
    return f"<span style='color:{STATUS[RISK_ROLE[level]]};font-size:1.1em'>{RISK_ICON[level]}</span> <b>{level}</b>"


def adv_for(city, row, advisories):
    d = row.time_pkt.tz_convert("Asia/Karachi").strftime("%Y-%m-%d")
    return advisories.get(f"{city}|{d}") or advisory.write(city, d, row.forecast_24h, row.hazard_prob, row.top_drivers, use_llm=False)


def forecast_view(today: pd.DataFrame, city: str, hourly: pd.DataFrame, advisories: dict, key: str, replay: bool):
    """Tiles, risk map, 48 h chart, SHAP drivers, what-if and the bilingual advisory for one issue time."""
    row = today.loc[city]
    tiles = st.columns(len(today))
    for col, (c, r) in zip(tiles, today.iterrows()):
        col.markdown(f"**{CITIES[c][0]}**<br><span style='font-size:1.6em'>{r.forecast_24h:.0f}</span> µg/m³<br>"
                     f"AQI {int(pm25_to_aqi(r.forecast_24h))} · {badge(r.risk_level)}<br>"
                     f"<span style='color:{INK_2};font-size:0.9em'>Chance of AQI &gt; 300: {r.hazard_prob:.0%}</span>",
                     unsafe_allow_html=True)

    left, right = st.columns([1, 1.4])
    with left:  # Scattergeo draws its own borders: no WebGL or tile server, works offline
        fig = go.Figure()
        for level in ["Green", "Yellow", "Orange", "Red"]:
            sub = today[today.risk_level == level]
            fig.add_trace(go.Scattergeo(
                lat=[CITIES[c][1] for c in sub.index], lon=[CITIES[c][2] for c in sub.index], mode="markers+text",
                marker=dict(size=20, color=STATUS[RISK_ROLE[level]], symbol=RISK_SYMBOL[level], line=dict(color="#ffffff", width=2)),
                name=level, text=[CITIES[c][0] for c in sub.index], textfont=dict(color=INK, size=13),
                textposition=["middle left" if c == "faisalabad" else "middle right" for c in sub.index],  # Faisalabad sits just west of Lahore
                customdata=np.stack([sub.forecast_24h.round(0), [int(pm25_to_aqi(v)) for v in sub.forecast_24h]], axis=-1) if len(sub) else None,
                hovertemplate="<b>%{text}</b><br>Next 24 h: %{customdata[0]} µg/m³<br>AQI %{customdata[1]}<extra></extra>"))
        fig.update_geos(lataxis_range=[23.5, 35.5], lonaxis_range=[64, 78.5], showcountries=True, countrycolor="#c3c2b7",
                        showcoastlines=True, coastlinecolor="#c3c2b7", showland=True, landcolor="#f3f2ee",
                        showocean=True, oceancolor="#e8f0fa", showframe=False, resolution=50)
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=430, title=dict(text="Forecast risk, next 24 hours", x=0),
                          legend=dict(orientation="h", y=-0.02, x=0), paper_bgcolor=SURFACE)
        st.plotly_chart(fig, width="stretch", key=f"{key}_map")

    with right:
        t0 = row.time_pkt.tz_convert("Asia/Karachi")
        obs = hourly[hourly.city == city].assign(t=lambda d: d.time_utc.dt.tz_convert("Asia/Karachi"))
        obs = obs[(obs.t > t0 - pd.Timedelta(days=5)) & (obs.t <= t0 + pd.Timedelta(hours=48))].sort_values("t")
        past, future = obs[obs.t <= t0], obs[obs.t > t0]
        d1, d2 = t0 + pd.Timedelta(hours=24), t0 + pd.Timedelta(hours=48)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=past.t, y=past.pm25, mode="lines", name="Observed (hourly)", line=dict(color=INK, width=1.6),
                                 hovertemplate="%{x|%d %b %H:%M}: %{y:.0f} µg/m³<extra></extra>"))
        if replay:
            fig.add_trace(go.Scatter(x=future.t, y=future.pm25, mode="lines", name="What actually happened",
                                     line=dict(color=MUTED, width=1.2, dash="dot"), hovertemplate="%{x|%d %b %H:%M}: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=[t0, d1, d1, t0], y=[row.q10, row.q10, row.q90, row.q90], fill="toself", mode="none",
                                 fillcolor="rgba(42,120,214,0.15)", name="80% range (next 24 h)", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[t0, d1], y=[row.forecast_24h] * 2, mode="lines", name="Forecast: next 24 h",
                                 line=dict(color="#2a78d6", width=3), hovertemplate="Next 24 h mean: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=[d1, d2], y=[row.forecast_48h] * 2, mode="lines", name="Forecast: 24-48 h",
                                 line=dict(color="#2a78d6", width=3, dash="dash"), hovertemplate="24-48 h mean: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_hline(y=HAZARDOUS_PM25, line=dict(color=STATUS["critical"], width=1, dash="dot"),
                      annotation_text="Hazardous (AQI 300)", annotation_position="top right", annotation_font_color=INK_2)
        fig.add_vline(x=t0, line=dict(color=MUTED, width=1))
        title = f"{CITIES[city][0]}: recent hours and the 48-hour forecast"
        fig.update_layout(title=dict(text=title, x=0), height=430, margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor=SURFACE,
                          hovermode="x unified", yaxis=dict(title="PM2.5 (µg/m³)", gridcolor=GRID, rangemode="tozero"),
                          xaxis=dict(gridcolor=GRID), legend=dict(orientation="h", y=-0.15, x=0, font=dict(size=11)))
        st.plotly_chart(fig, width="stretch", key=f"{key}_chart")

    why, whatif = st.columns([1.2, 1])
    with why:
        st.markdown("#### Why this forecast?")
        groups = list(DRIVERS)
        vals = [row[f"shap_{g}"] for g in groups]
        order = np.argsort(vals)
        fig = go.Figure(go.Bar(x=[vals[i] for i in order], y=[groups[i] for i in order], orientation="h",
                               marker=dict(color=[DRIVERS[groups[i]] for i in order]), text=[f"{vals[i]:+.0f}" for i in order],
                               textposition="outside", hovertemplate="%{y}: %{x:+.0f} µg/m³<extra></extra>"))
        fig.update_layout(height=250, margin=dict(l=10, r=40, t=10, b=10), plot_bgcolor=SURFACE,
                          xaxis=dict(title="µg/m³ above or below the typical level", gridcolor=GRID, zeroline=True, zerolinecolor="#c3c2b7"))
        st.plotly_chart(fig, width="stretch", key=f"{key}_why")
        top = json.loads(row.top_drivers)
        st.caption(f"Typical level {row.shap_base:.0f} µg/m³ + driver contributions = {row.forecast_24h:.0f} µg/m³. "
                   "Strongest single factors: " + "; ".join(f"{d['label']} ({d['ug_m3']:+.0f})" for d in top) +
                   ". SHAP shows what the model relied on: statistical, not a chemical source measurement.")
    with whatif:
        st.markdown("#### What if there were fewer crop fires?")
        cut = st.slider("Reduce upwind crop fires by", 0, 100, 0, step=10, format="%d%%", key=f"{key}_cut")
        new = row[f"whatif_{cut}"]
        st.metric("Forecast, next 24 h", f"{new:.0f} µg/m³",
                  delta=f"{new - row.forecast_24h:+.0f} µg/m³ vs actual fire levels" if cut else None, delta_color="inverse")
        st.caption(f"AQI {int(pm25_to_aqi(new))}, {risk_level(new)[0]}. A model-based estimate: fire features are scaled down and the "
                   "forecast recomputed, everything else fixed. The model is constrained so that fewer fires never raise a forecast.")

    st.markdown("#### Health advisory · صحت سے متعلق ہدایات")
    adv = adv_for(city, row, advisories)
    a1, a2 = st.columns(2)
    a1.info(adv["en"])
    a2.markdown(f"<div dir='rtl' style='background:#eef5fd;padding:12px 16px;border-radius:8px;font-size:1.1em;line-height:1.9'>"
                f"{adv['ur'].replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
    st.caption("Source: " + ("AI Smog Explainer (LLM, numbers taken from the model, checked automatically)"
                             if adv.get("source") != "template" else "rule-based bilingual template (no LLM answer for this day)"))
    if replay and pd.notna(row.target_24h):
        st.caption(f"Replay check: the next 24 hours actually averaged {row.target_24h:.0f} µg/m³ (AQI {int(pm25_to_aqi(row.target_24h))}).")


# ---------------- page ----------------
st.markdown("## SAANS · Smog forecast for Pakistan's cities, and why")
st.caption("24- and 48-hour PM2.5 forecasts for Lahore, Faisalabad, Multan, Islamabad and Karachi, explained with SHAP and "
           "translated into English and Urdu advice. Built from OpenAQ sensors, NASA FIRMS fires, ERA5/Open-Meteo weather and an LLM news calendar.")
daily, hourly, advisories, evaluation = load_replay()
tab_live, tab_replay, tab_how, tab_data, tab_dq, tab_perf, tab_about = st.tabs(
    ["Live forecast", "Replay: test seasons", "How the data was made", "Cleaned data", "Data quality", "Model performance", "About"])

with tab_how:
    import re
    doc = (ROOT / "docs" / "DATA_PIPELINE.md").read_text(encoding="utf-8")
    doc = re.sub(r"```mermaid.*?```", "**Flow:** APIs → `data/raw/` (untouched responses) → `data/interim/` (one table per source) → "
                 "notebook 02, nine cleaning steps → `data/processed/` (master table + CSVs) and the Data Quality Report", doc, flags=re.S)
    doc = re.sub(r"\]\(\.\./", "](https://github.com/FarhanRajputFelix/saans/blob/main/", doc)  # links point at the repository
    st.markdown(doc)

with tab_live:
    res, mode = None, None
    if HAVE_KEYS:
        c1, c2 = st.columns([3, 1])
        if c2.button("Refresh now", help="Fetch the latest data again (otherwise reused for up to an hour)"):
            run_live.clear()
        with st.spinner("Fetching the last four days of sensor, weather and fire data, then forecasting (about a minute)..."):
            try:
                res, mode = run_live(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H")), "live"
                if res["forecasts"].empty:
                    res = None
            except Exception as e:
                st.warning(f"Live run failed ({type(e).__name__}); showing the latest snapshot instead.")
    if res is None:
        res, mode = load_snapshot(), "snapshot"
    if not HAVE_KEYS:
        seen = {k: bool(os.getenv(k)) for k in KEY_NAMES}
        st.caption("API keys the app can see: " + " · ".join(f"{k} {'found' if v else 'missing'}" for k, v in seen.items())
                   + ". The live forecast needs OPENAQ_API_KEY (FIRMS_MAP_KEY adds fire data; GEMINI/GROQ write the advisory).")
    if res is None or res["forecasts"].empty:
        st.error("No live forecast available: add API keys in the app's secrets (see About).")
    else:
        fc = res["forecasts"].set_index("city")
        issued = fc.time_pkt.max().tz_convert("Asia/Karachi")
        if mode == "live":
            st.success(f"Live forecast issued {issued:%a %d %b %Y, %H:%M} Pakistan time, from data fetched just now.")
        else:
            st.info(f"Snapshot of a live run issued {issued:%a %d %b %Y, %H:%M} Pakistan time (committed to the repository). "
                    "Add API keys in the app's secrets to forecast live from fresh data.")
        status = res["status"]
        fires = status.get("fires", {})
        if not fires.get("fresh"):
            st.warning("NASA FIRMS did not answer during this run, so the forecast was made **without fresh fire data** (fire features "
                       "set to zero). The upwind-fire driver and the what-if slider are not meaningful for this run.")
        with st.expander("Data behind this forecast (what each source returned)"):
            rows = [{"city": CITIES[c][0], **{k: v for k, v in info.items()}} for c, info in status["cities"].items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption(f"Fires: {fires.get('detections', 0)} cleaned detections from {', '.join(fires.get('sources', [])) or 'no source'}"
                       + (f"; problems: {'; '.join(fires.get('errors', []))}" if fires.get("errors") else "") +
                       ". Weather: Open-Meteo forecast API (last 4 days). PM2.5: OpenAQ sensors reporting in the last 2 days, "
                       "cleaned with the rules of notebook 02.")
        live_cities = [c for c in CITIES if c in fc.index]
        city = st.selectbox("City", live_cities, format_func=lambda c: CITIES[c][0], key="live_city")
        forecast_view(fc, city, res["observed"], res.get("advisories", {}), key="live", replay=False)
        st.caption("Known limits of the live mode: weather comes from the Open-Meteo forecast model rather than ERA5; the news event "
                   "calendar is not updated live (event features are zero); Lahore's low-cost network reads lower than the reference "
                   "monitor the model learned on, so Lahore forecasts tend to run about 26 µg/m³ high (see the findings log).")

with tab_replay:
    c1, c2, c3 = st.columns([1, 1, 2])
    season = c1.selectbox("Smog season", ["2024-25", "2025-26"], index=0, key="rp_season")
    s = daily[daily.season == season]
    cities_here = [c for c in CITIES if c in set(s.city)]
    city_r = c2.selectbox("City", cities_here, format_func=lambda c: CITIES[c][0], key="rp_city",
                          index=cities_here.index("lahore") if "lahore" in cities_here else 0)
    dates = sorted(s[s.city == city_r].date.unique())
    default = pd.Timestamp("2024-11-06").date() if season == "2024-25" else dates[len(dates) // 2]
    date = c3.select_slider("Forecast date (issued 08:00)", options=dates, value=default if default in dates else dates[0],
                            format_func=lambda d: pd.Timestamp(d).strftime("%a %d %b %Y"), key="rp_date")
    st.caption("Replays forecasts on the two held-out test seasons, which the models never saw, so you can compare each forecast "
               "with what actually happened.")
    forecast_view(s[s.date == date].set_index("city"), city_r, hourly, advisories, key="replay", replay=True)

with tab_data:
    st.markdown("### The cleaned hourly master table")
    st.markdown("This is the dataset produced by the nine cleaning steps of notebook 02: **one row per city per hour**, "
                "1 Jan 2020 to 31 Jan 2026, 266,760 rows. Choose a city and dates to view it, and download your selection as CSV. "
                "The full files are in the repository under `data/processed/` (Parquet, plus one CSV per city in `data/processed/csv/`).")
    master = load_master()
    c1, c2, c3 = st.columns([1, 1.4, 1])
    dcity = c1.selectbox("City", list(CITIES), format_func=lambda c: CITIES[c][0], key="data_city")
    picked = c2.date_input("Dates (Pakistan time)", value=(pd.Timestamp("2024-11-01").date(), pd.Timestamp("2024-11-07").date()),
                           min_value=pd.Timestamp("2020-01-01").date(), max_value=pd.Timestamp("2026-01-31").date(), key="data_dates")
    start, end = (picked if isinstance(picked, (tuple, list)) and len(picked) == 2 else (picked[0], picked[0]) if isinstance(picked, (tuple, list)) else (picked, picked))
    view = c3.radio("Columns", ["Key columns", "All columns"], horizontal=True, key="data_cols")
    local = master.time_pkt.dt.tz_convert("Asia/Karachi").dt.tz_localize(None)
    sel = master[(master.city == dcity) & (local >= pd.Timestamp(start)) & (local < pd.Timestamp(end) + pd.Timedelta(days=1))].copy()
    sel.insert(1, "time_pkt_str", sel.time_pkt.dt.tz_convert("Asia/Karachi").dt.strftime("%Y-%m-%d %H:%M"))
    key_cols = ["city", "time_pkt_str", "pm25", "pm25_source", "pm25_interpolated", "long_gap", "extreme_event", "pm10",
                "boundary_layer_height", "blh_imputed", "wind_speed_10m", "wind_direction_10m", "relative_humidity_2m",
                "temperature_2m", "fires_300km", "frp_300km"]
    shown = sel[key_cols] if view == "Key columns" else sel.drop(columns=["time_pkt"])
    st.caption(f"{len(sel):,} rows · PM2.5 present in {sel.pm25.notna().mean():.0%} of them · "
               f"{int(sel.extreme_event.sum())} extreme-event hours (PM2.5 ≥ 250)")
    st.dataframe(shown.rename(columns={"time_pkt_str": "time (PKT)"}), hide_index=True, width="stretch", height=420)
    st.download_button("Download this selection (CSV)", shown.to_csv(index=False).encode("utf-8"),
                       file_name=f"saans_{dcity}_{start}_{end}.csv", mime="text/csv")
    p = ROOT / "data" / "README.md"
    if p.exists():
        with st.expander("What every column means"):
            st.markdown(p.read_text(encoding="utf-8").split("## Columns of the master table", 1)[-1].split("\n## ", 1)[0])

with tab_dq:
    st.markdown("Cleaning is the core of the project: nine steps, every one logged with before and after counts (notebook 02).")
    sens_path = ROOT / "data" / "interim" / "openaq_sensors.csv"
    if sens_path.exists():
        sens = pd.read_csv(sens_path)
        sens = sens[(sens.parameter == "pm25") & (sens.days_in_period > 0)].drop_duplicates("sensor_id")
        fig = go.Figure()
        for kind, color, name in [(False, "#eb6834", "Low-cost sensor"), (True, "#2a78d6", "Reference monitor")]:
            k = sens[sens.is_monitor == kind]
            fig.add_trace(go.Scattergeo(lat=k.lat, lon=k.lon, mode="markers", name=f"{name} ({len(k)})",
                                        marker=dict(size=11 if kind else 7, color=color, line=dict(color="#ffffff", width=1)),
                                        text=k.location + " · " + k.provider.fillna(""), hovertemplate="%{text}<extra></extra>"))
        fig.update_geos(lataxis_range=[23.8, 34.5], lonaxis_range=[66, 75.5], showcountries=True, countrycolor="#c3c2b7",
                        showland=True, landcolor="#f3f2ee", showocean=True, oceancolor="#e8f0fa", showframe=False, resolution=50)
        fig.update_layout(title=dict(text="Where the PM2.5 sensors are: coverage clusters in a few neighbourhoods", x=0),
                          height=480, margin=dict(l=0, r=0, t=40, b=0), legend=dict(orientation="h", y=-0.02), paper_bgcolor=SURFACE)
        st.plotly_chart(fig, width="stretch", key="sensor_map")
        st.caption("A data-equity finding: only 4 reference monitors exist (US diplomatic posts in Lahore, Islamabad, Karachi, plus a "
                   "second feed of the Islamabad monitor) and their feed stopped on 4 March 2025. Faisalabad and Multan have only "
                   "low-cost sensors, from June 2025.")
    p = REPORTS / "data_quality_report.md"
    if p.exists():
        st.markdown(p.read_text(encoding="utf-8").split("\n", 2)[-1])
    for fig_name, cap in [("sensor_coverage.png", "Sensor coverage over time"), ("blh_imputation_check.png", "Boundary layer height imputation check")]:
        fp = REPORTS / "figures" / fig_name
        if fp.exists():
            st.image(str(fp), caption=cap)

with tab_perf:
    st.markdown("Trained on 1 Jan 2020 to 28 Sep 2024; tested on the 2024-25 and 2025-26 smog seasons, which the models never saw. "
                "Skill = 1 − MAE(model) / MAE(persistence): above 0 beats persistence.")
    st.markdown("**24-hour mean PM2.5 forecasts, all cities (MAE in µg/m³)**")
    st.dataframe(pd.DataFrame(evaluation["regression"]), hide_index=True, width="stretch")
    p = REPORTS / "evaluation_regression.csv"
    if p.exists():
        st.markdown("**Per city** (Faisalabad and Multan were never in training)")
        st.dataframe(pd.read_csv(p), hide_index=True, width="stretch")
    st.markdown("**Hazard warnings (next 24 h above AQI 300)**")
    st.dataframe(pd.DataFrame(evaluation["classifier"]), hide_index=True, width="stretch")
    for fig_name in ["forecast_lahore_nov2024.png", "shap_groups.png", "shap_top_features.png"]:
        fp = REPORTS / "figures" / fig_name
        if fp.exists():
            st.image(str(fp))

with tab_about:
    st.markdown("""
**SAANS** (Smog Attribution And Nowcasting System). *Saans* means breath in Urdu.

* **Data:** OpenAQ v3 (PM2.5, PM10), NASA FIRMS (VIIRS and MODIS fires), Open-Meteo (ERA5 history; forecast API for the live mode), GDELT news headlines.
* **Models:** LightGBM regressors (next 24 h and 24-48 h, predicting the change from the last 24 hours), quantile models for the 80% range, a LightGBM hazard classifier; SHAP for attribution; fire features constrained so more fire never lowers a forecast.
* **LLM:** Gemini (Groq fallback) extracts the event calendar from headlines and writes the bilingual advisories. It only rewords the model's numbers, and every number it writes is checked.
* **Limits:** attribution is statistical, not chemical; Faisalabad and Multan have sensors only from June 2025; the live mode depends on the APIs answering.

**Enable the live forecast on Streamlit Cloud:** app menu → Settings → Secrets, then paste (one per line, values in quotes, no section header needed):
```
OPENAQ_API_KEY = "your key"
FIRMS_MAP_KEY = "your key"
GEMINI_API_KEY = "your key"
GROQ_API_KEY = "your key"
```

Data Science course project, SZABIST University Karachi. Code and notebooks: github.com/FarhanRajputFelix/saans
""")
