"""SAANS dashboard: today's smog forecast for five Pakistani cities, the reasons, and the data behind it.

Tabs
- Live forecast: opens instantly on the latest snapshot; "Fetch live forecast" downloads the last four days
  of sensor, weather and fire data and forecasts from them (needs OPENAQ_API_KEY and FIRMS_MAP_KEY in the
  app's secrets; GEMINI_API_KEY or GROQ_API_KEY for the LLM advisory). A live run is reused for an hour.
- Replay: the two held-out test seasons day by day, with what actually happened.
- How the data was made, Cleaned data, Data quality, Model performance, About.

Local run:  streamlit run app/streamlit_app.py
"""
import json
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="SAANS · Smog forecast", page_icon="🌫️", layout="wide", initial_sidebar_state="collapsed")

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
from saans.aqi import BREAKPOINTS, CATEGORY_COLORS, HAZARDOUS_PM25, SHORT_NAMES, category, pm25_to_aqi  # noqa: E402

# saans.config read the keys when the process first started; refresh its copies so keys added later take effect
config.OPENAQ_API_KEY = os.getenv("OPENAQ_API_KEY", "") or config.OPENAQ_API_KEY
config.FIRMS_MAP_KEY = os.getenv("FIRMS_MAP_KEY", "") or config.FIRMS_MAP_KEY

DATA = ROOT / "app" / "data"
REPORTS = ROOT / "reports"
PROCESSED = ROOT / "data" / "processed"
CITIES = {"lahore": ("Lahore", 31.5497, 74.3436), "faisalabad": ("Faisalabad", 31.4504, 73.1350),
          "multan": ("Multan", 30.1575, 71.5249), "islamabad": ("Islamabad", 33.6844, 73.0479),
          "karachi": ("Karachi", 24.8607, 67.0011)}
# dark-mode palette (validated categorical steps) and chart chrome
DRIVERS = {"Recent pollution": "#3987e5", "Weather": "#d95926", "Upwind fires": "#199e70", "Calendar": "#c98500"}
INK, INK_2, MUTED, GRID, AXIS, SURFACE = "#f0efec", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#1a1a19"
BLUE, RED = "#3987e5", "#e66767"
HAVE_KEYS = bool(config.OPENAQ_API_KEY)
HAVE_LLM = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY"))

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Noto+Nastaliq+Urdu:wght@400;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, button, input { font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', sans-serif; }
.stApp { background:
  radial-gradient(1100px 520px at 0% -8%, rgba(57,135,229,.20), transparent 60%),
  radial-gradient(900px 480px at 100% -4%, rgba(217,89,38,.16), transparent 55%),
  #0b0e14; }
.block-container { padding-top: 1.4rem; max-width: 1420px; }
.hero { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; flex-wrap:wrap; margin-bottom:6px; }
.hero h1 { font-size: 2.5rem; font-weight: 800; letter-spacing:-.02em; margin:0; line-height:1.1;
  background: linear-gradient(90deg, #f0efec 0%, #9ec5f4 45%, #ec835a 100%); -webkit-background-clip: text; background-clip:text; color: transparent; }
.hero p { color: #c3c2b7; margin: 6px 0 0; max-width: 860px; }
.badge { display:inline-flex; align-items:center; gap:8px; padding:5px 12px; border-radius:999px; font-weight:600; font-size:.82rem; }
.badge.live { background: rgba(12,163,12,.14); color:#8be38b; border:1px solid rgba(12,163,12,.45); }
.badge.snap { background: rgba(250,178,25,.12); color:#f6cf74; border:1px solid rgba(250,178,25,.40); }
.badge .dot { width:9px; height:9px; border-radius:50%; background: currentColor; animation: pulse 1.8s infinite; }
@keyframes pulse { 0% {box-shadow:0 0 0 0 rgba(139,227,139,.55)} 70% {box-shadow:0 0 0 10px rgba(139,227,139,0)} 100% {box-shadow:0 0 0 0 rgba(139,227,139,0)} }
.cards { display:grid; grid-template-columns: repeat(auto-fit, minmax(175px, 1fr)); gap:14px; margin: 8px 0 16px; }
.card { position:relative; padding:18px 16px 14px; border-radius:18px; overflow:hidden;
  background: linear-gradient(160deg, rgba(255,255,255,.08), rgba(255,255,255,.02));
  border: 1px solid rgba(255,255,255,.09); box-shadow: 0 14px 34px rgba(0,0,0,.38);
  transition: transform .25s ease, box-shadow .25s ease; transform: perspective(700px); }
.card:hover { transform: perspective(700px) rotateX(3deg) translateY(-4px); box-shadow: 0 22px 44px rgba(0,0,0,.5); }
.card .accent { position:absolute; left:0; right:0; top:0; height:4px; }
.card .glow { position:absolute; right:-40px; top:-40px; width:120px; height:120px; border-radius:50%; filter: blur(30px); opacity:.35; }
.card.selected { border-color: rgba(57,135,229,.75); box-shadow: 0 0 0 1px rgba(57,135,229,.55), 0 14px 34px rgba(0,0,0,.38); }
.card .city { color:#c3c2b7; font-weight:600; font-size:.88rem; letter-spacing:.03em; text-transform:uppercase; }
.card .value { color:#f0efec; font-size:2.3rem; font-weight:800; line-height:1.05; margin-top:8px; }
.card .unit { color:#898781; font-size:.85rem; font-weight:500; }
.card .pill { display:inline-flex; align-items:center; gap:7px; margin-top:10px; padding:3px 10px; border-radius:999px;
  background: rgba(255,255,255,.07); color:#f0efec; font-size:.78rem; font-weight:600; }
.card .pill i { width:10px; height:10px; border-radius:50%; display:inline-block; }
.card .sub { color:#898781; font-size:.78rem; margin-top:7px; }
.legend { display:flex; flex-wrap:wrap; gap:8px; margin: 2px 0 8px; }
.legend span { display:inline-flex; align-items:center; gap:6px; font-size:.75rem; color:#c3c2b7; padding:3px 9px; border-radius:999px; background: rgba(255,255,255,.05); }
.legend i { width:10px; height:10px; border-radius:3px; display:inline-block; }
.panel-title { color:#f0efec; font-weight:700; font-size:1.05rem; margin: 6px 0 4px; }
.adv { padding:16px 18px; border-radius:16px; color:#f0efec; line-height:1.75;
  background: linear-gradient(160deg, rgba(57,135,229,.18), rgba(57,135,229,.05)); border: 1px solid rgba(57,135,229,.35); }
.adv.ur { direction: rtl; text-align:right; font-family: 'Noto Nastaliq Urdu', 'Jameel Noori Nastaleeq', serif; font-size: 1.08rem; line-height: 2.25; }
.stTabs [data-baseweb="tab-list"] { gap:6px; padding:6px; border-radius:14px; background: rgba(255,255,255,.04); border:1px solid rgba(255,255,255,.07); flex-wrap: wrap; }
.stTabs [data-baseweb="tab"] { border-radius:10px; padding:7px 14px; height:auto; }
.stTabs [aria-selected="true"] { background: rgba(57,135,229,.25); }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display:none; }
div[data-testid="stMetricValue"] { font-weight:800; }
</style>
""", unsafe_allow_html=True)


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


@st.cache_data
def load_fires():
    return pd.read_parquet(PROCESSED / "fires_clean.parquet", columns=["latitude", "longitude", "frp", "hour_utc"])


@st.cache_data(ttl=3600, show_spinner=False)
def run_live(hour_key: str):
    """At most one live run per hour, shared by all visitors (hour_key changes every hour)."""
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


# ---------------- building blocks ----------------
def rgba(hex_color: str, alpha: int = 235) -> list[int]:
    h = hex_color.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)] + [alpha]


def style(fig, height):
    fig.update_layout(height=height, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(color=INK_2, family="Inter, system-ui, sans-serif"),
                      hoverlabel=dict(bgcolor=SURFACE, font_color=INK, bordercolor=AXIS),
                      xaxis=dict(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS),
                      yaxis=dict(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS))
    return fig


def city_cards(today: pd.DataFrame, selected: str) -> str:
    cards = []
    for c, r in today.iterrows():
        cat = category(r.forecast_24h)
        col = CATEGORY_COLORS[cat]
        cards.append(
            f"<div class='card{' selected' if c == selected else ''}'><div class='accent' style='background:{col}'></div>"
            f"<div class='glow' style='background:{col}'></div><div class='city'>{CITIES[c][0]}</div>"
            f"<div class='value'>{r.forecast_24h:.0f} <span class='unit'>µg/m³</span></div>"
            f"<div class='pill'><i style='background:{col}'></i>AQI {int(pm25_to_aqi(r.forecast_24h))} · {SHORT_NAMES.get(cat, cat)}</div>"
            f"<div class='sub'>Chance of AQI &gt; 300: {r.hazard_prob:.0%}</div></div>")
    return "<div class='cards'>" + "".join(cards) + "</div>"


def legend_html() -> str:
    items = [f"<span><i style='background:{CATEGORY_COLORS[c]}'></i>{c} · {lo:g}-{hi:g}</span>" if hi < 300
             else f"<span><i style='background:{CATEGORY_COLORS[c]}'></i>{c} · {lo:g}+</span>" for lo, hi, a, b, c in BREAKPOINTS]
    return "<div class='legend'>" + "".join(items) + "<span>PM2.5 24-hour mean, µg/m³ (US EPA)</span></div>"


def map3d(today: pd.DataFrame, fires: pd.DataFrame | None, key: str):
    """3D map: one column per city (height = forecast, colour = EPA category) and the fires of the
    previous three days as 3D hexagons (height = number of detections)."""
    cities = pd.DataFrame([{
        "name": CITIES[c][0], "lat": CITIES[c][1], "lon": CITIES[c][2], "value": int(round(r.forecast_24h)),
        "aqi": int(pm25_to_aqi(r.forecast_24h)), "cat": category(r.forecast_24h),
        "color": rgba(CATEGORY_COLORS[category(r.forecast_24h)]), "label": f"{CITIES[c][0]} {r.forecast_24h:.0f}",
        "dx": -70 if c == "faisalabad" else 0}  # Faisalabad sits just west of Lahore: label it to the left
        for c, r in today.iterrows()])
    layers = []
    if fires is not None and len(fires):
        layers.append(pdk.Layer(
            "HexagonLayer", data=fires[["longitude", "latitude"]], get_position="[longitude, latitude]", radius=9000,
            extruded=True, elevation_scale=90, elevation_range=[0, 1200], coverage=0.88, opacity=0.6, pickable=False,
            color_range=[[255, 237, 160], [254, 217, 118], [254, 178, 76], [253, 141, 60], [240, 59, 32], [189, 0, 38]]))
    layers.append(pdk.Layer(
        "ColumnLayer", data=cities, get_position="[lon, lat]", get_elevation="value", elevation_scale=900, radius=17000,
        get_fill_color="color", extruded=True, pickable=True, auto_highlight=True))
    layers.append(pdk.Layer(
        "TextLayer", data=cities, get_position="[lon, lat]", get_text="label", get_size=15, get_color=[240, 239, 236],
        get_pixel_offset="[dx, 18]", get_alignment_baseline="'top'", background=True, get_background_color=[11, 14, 20, 210],
        background_padding=[6, 3, 6, 3]))
    deck = pdk.Deck(layers=layers, map_provider="carto", map_style=pdk.map_styles.CARTO_DARK_NO_LABELS,
                    initial_view_state=pdk.ViewState(latitude=28.4, longitude=71.6, zoom=5.25, pitch=50, bearing=-12),
                    tooltip={"html": "<b>{name}</b><br/>Next 24 h: {value} µg/m³<br/>AQI {aqi} · {cat}",
                             "style": {"backgroundColor": SURFACE, "color": INK, "fontFamily": "Inter, sans-serif"}})
    st.pydeck_chart(deck, height=470, key=key)


def adv_for(city, row, advisories):
    d = row.time_pkt.tz_convert("Asia/Karachi").strftime("%Y-%m-%d")
    return advisories.get(f"{city}|{d}") or advisory.write(city, d, row.forecast_24h, row.hazard_prob, row.top_drivers, use_llm=False)


def forecast_view(today: pd.DataFrame, city: str, hourly: pd.DataFrame, fires: pd.DataFrame | None, advisories: dict,
                  key: str, replay: bool):
    """Cards, 3D map, 48 h chart, SHAP drivers, what-if and the bilingual advisory for one issue time."""
    row = today.loc[city]
    st.markdown(city_cards(today, city), unsafe_allow_html=True)

    left, right = st.columns([1.15, 1])
    with left:
        st.markdown("<div class='panel-title'>Forecast risk and upwind fires, in 3D</div>", unsafe_allow_html=True)
        map3d(today, fires, key=f"{key}_map")
        st.markdown(legend_html(), unsafe_allow_html=True)
        st.caption("Column height = next-24 h PM2.5 forecast; colour = US EPA category. Orange hexagons = satellite fire "
                   "detections in the 72 hours before the forecast (taller = more fires). Drag to rotate, scroll to zoom.")
    with right:
        t0 = row.time_pkt.tz_convert("Asia/Karachi")
        obs = hourly[hourly.city == city].assign(t=lambda d: d.time_utc.dt.tz_convert("Asia/Karachi"))
        obs = obs[(obs.t > t0 - pd.Timedelta(days=5)) & (obs.t <= t0 + pd.Timedelta(hours=48))].sort_values("t")
        past, future = obs[obs.t <= t0], obs[obs.t > t0]
        d1, d2 = t0 + pd.Timedelta(hours=24), t0 + pd.Timedelta(hours=48)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=past.t, y=past.pm25, mode="lines", name="Observed (hourly)", line=dict(color=INK, width=1.6),
                                 fill="tozeroy", fillcolor="rgba(240,239,236,.05)", hovertemplate="%{x|%d %b %H:%M}: %{y:.0f} µg/m³<extra></extra>"))
        if replay:
            fig.add_trace(go.Scatter(x=future.t, y=future.pm25, mode="lines", name="What actually happened",
                                     line=dict(color=MUTED, width=1.3, dash="dot"), hovertemplate="%{x|%d %b %H:%M}: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=[t0, d1, d1, t0], y=[row.q10, row.q10, row.q90, row.q90], fill="toself", mode="none",
                                 fillcolor="rgba(57,135,229,.22)", name="80% range (next 24 h)", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[t0, d1], y=[row.forecast_24h] * 2, mode="lines", name="Forecast: next 24 h",
                                 line=dict(color=BLUE, width=4), hovertemplate="Next 24 h mean: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=[d1, d2], y=[row.forecast_48h] * 2, mode="lines", name="Forecast: 24-48 h",
                                 line=dict(color=BLUE, width=4, dash="dash"), hovertemplate="24-48 h mean: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_hline(y=HAZARDOUS_PM25, line=dict(color=RED, width=1, dash="dot"), annotation_text="Hazardous (AQI 300)",
                      annotation_position="top right", annotation_font_color=INK_2)
        fig.add_vline(x=t0, line=dict(color=MUTED, width=1))
        style(fig, 470)
        fig.update_layout(title=dict(text=f"{CITIES[city][0]}: recent hours and the 48-hour forecast", x=0, font=dict(color=INK, size=15)),
                          margin=dict(l=10, r=10, t=40, b=10), hovermode="x unified", yaxis_title="PM2.5 (µg/m³)",
                          yaxis_rangemode="tozero", legend=dict(orientation="h", y=-0.16, x=0, font=dict(size=11)))
        st.plotly_chart(fig, width="stretch", key=f"{key}_chart")

    why, whatif = st.columns([1.25, 1])
    with why:
        st.markdown("<div class='panel-title'>Why this forecast?</div>", unsafe_allow_html=True)
        groups = list(DRIVERS)
        vals = [row[f"shap_{g}"] for g in groups]
        order = np.argsort(vals)
        fig = go.Figure(go.Bar(x=[vals[i] for i in order], y=[groups[i] for i in order], orientation="h",
                               marker=dict(color=[DRIVERS[groups[i]] for i in order], cornerradius=5), text=[f"{vals[i]:+.0f}" for i in order],
                               textposition="outside", textfont=dict(color=INK_2), hovertemplate="%{y}: %{x:+.0f} µg/m³<extra></extra>"))
        style(fig, 250)
        fig.update_layout(margin=dict(l=10, r=40, t=10, b=10), xaxis_title="µg/m³ above or below the typical level")
        st.plotly_chart(fig, width="stretch", key=f"{key}_why")
        top = json.loads(row.top_drivers)
        st.caption(f"Typical level {row.shap_base:.0f} µg/m³ + driver contributions = {row.forecast_24h:.0f} µg/m³. "
                   "Strongest single factors: " + "; ".join(f"{d['label']} ({d['ug_m3']:+.0f})" for d in top) +
                   ". SHAP shows what the model relied on: statistical, not a chemical source measurement.")
    with whatif:
        st.markdown("<div class='panel-title'>What if there were fewer crop fires?</div>", unsafe_allow_html=True)
        cut = st.slider("Reduce upwind crop fires by", 0, 100, 0, step=10, format="%d%%", key=f"{key}_cut")
        new = row[f"whatif_{cut}"]
        st.metric("Forecast, next 24 h", f"{new:.0f} µg/m³",
                  delta=f"{new - row.forecast_24h:+.0f} µg/m³ vs actual fire levels" if cut else None, delta_color="inverse")
        st.caption(f"AQI {int(pm25_to_aqi(new))}, {category(new)}. A model-based estimate: fire features are scaled down and the "
                   "forecast recomputed, everything else fixed. The model is constrained so fewer fires never raise a forecast.")

    st.markdown("<div class='panel-title'>Health advisory · صحت سے متعلق ہدایات</div>", unsafe_allow_html=True)
    adv = adv_for(city, row, advisories)
    a1, a2 = st.columns(2)
    a1.markdown(f"<div class='adv'>{adv['en'].replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
    a2.markdown(f"<div class='adv ur'>{adv['ur'].replace(chr(10), '<br>')}</div>", unsafe_allow_html=True)
    st.caption("Source: " + ("AI Smog Explainer (LLM, numbers taken from the model, checked automatically)"
                             if adv.get("source") != "template" else "rule-based bilingual template (no LLM answer for this day)"))
    if replay and pd.notna(row.target_24h):
        st.caption(f"Replay check: the next 24 hours actually averaged {row.target_24h:.0f} µg/m³ "
                   f"(AQI {int(pm25_to_aqi(row.target_24h))}, {category(row.target_24h)}).")


# ---------------- page ----------------
daily, hourly, advisories, evaluation = load_replay()

if "live" not in st.session_state:
    st.session_state.live = None
res = st.session_state.live or load_snapshot()
mode = "live" if st.session_state.live else "snapshot"

badge = ("<span class='badge live'><span class='dot'></span>LIVE</span>" if mode == "live"
         else "<span class='badge snap'><span class='dot'></span>LATEST SNAPSHOT</span>")
st.markdown(f"""<div class='hero'><div><h1>SAANS · Smog forecast for Pakistan</h1>
<p>Next 24 and 48 hours of PM2.5 for Lahore, Faisalabad, Multan, Islamabad and Karachi, explained with SHAP and turned into
English and Urdu advice. Built from OpenAQ sensors, NASA FIRMS fires, ERA5/Open-Meteo weather and an LLM news calendar.</p></div>
<div>{badge}</div></div>""", unsafe_allow_html=True)

tab_live, tab_replay, tab_how, tab_data, tab_dq, tab_perf, tab_about = st.tabs(
    ["Live forecast", "Replay: test seasons", "How the data was made", "Cleaned data", "Data quality", "Model performance", "About"])

with tab_live:
    c1, c2 = st.columns([3, 1.2])
    with c2:
        if HAVE_KEYS and st.button("Fetch live forecast (about a minute)", type="primary", width="stretch",
                                   help="Downloads the last four days of sensor, weather and fire data. Reused for up to an hour."):
            fresh = None
            with st.spinner("Fetching the last four days of sensor, weather and fire data, then forecasting..."):
                try:
                    fresh = run_live(pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H"))
                except Exception as e:
                    st.warning(f"Live run failed ({type(e).__name__}); the latest snapshot is shown instead.")
            if fresh is not None and not fresh["forecasts"].empty:
                st.session_state.live = fresh
                st.rerun()  # outside the try: st.rerun works by raising an exception
    if res is None or res["forecasts"].empty:
        st.error("No forecast available yet.")
    else:
        fc = res["forecasts"].set_index("city")
        issued = fc.time_pkt.max().tz_convert("Asia/Karachi")
        with c1:
            if mode == "live":
                st.success(f"Live forecast issued {issued:%a %d %b %Y, %H:%M} Pakistan time, from data fetched just now.")
            else:
                st.info(f"Latest snapshot: forecast issued {issued:%a %d %b %Y, %H:%M} Pakistan time"
                        + (". Press the button for a live forecast from fresh data." if HAVE_KEYS else
                           ". Add API keys in the app's secrets to enable live forecasts."))
        if not HAVE_KEYS:
            seen = {k: bool(os.getenv(k)) for k in KEY_NAMES}
            st.caption("API keys the app can see: " + " · ".join(f"{k} {'found' if v else 'missing'}" for k, v in seen.items()))
        status = res["status"]
        fires_info = status.get("fires", {})
        if not fires_info.get("fresh"):
            st.warning("NASA FIRMS did not answer during this run, so the forecast was made **without fresh fire data** (fire features "
                       "set to zero). The upwind-fire driver and the what-if slider are not meaningful for this run.")
        with st.expander("Data behind this forecast (what each source returned)"):
            rows = [{"city": CITIES[c][0], **{k: v for k, v in info.items()}} for c, info in status["cities"].items()]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            st.caption(f"Fires: {fires_info.get('detections', 0)} cleaned detections from {', '.join(fires_info.get('sources', [])) or 'no source'}"
                       + (f"; problems: {'; '.join(fires_info.get('errors', []))}" if fires_info.get("errors") else "") +
                       ". Weather: Open-Meteo forecast API (last 4 days). PM2.5: OpenAQ sensors reporting in the last 2 days, "
                       "cleaned with the rules of notebook 02.")
        live_cities = [c for c in CITIES if c in fc.index]
        city = st.selectbox("City", live_cities, format_func=lambda c: CITIES[c][0], key="live_city")
        fires = res.get("fires")
        if fires is not None and len(fires):
            t0 = fc.time_utc.max()
            fires = fires[(fires.hour_utc > t0 - pd.Timedelta(hours=72)) & (fires.hour_utc <= t0)]
        forecast_view(fc, city, res["observed"], fires, res.get("advisories", {}), key="live", replay=False)
        st.caption("Known limits of the live mode: weather comes from the Open-Meteo forecast model rather than ERA5, and the news "
                   "event calendar is not updated live (event features are zero; the calendar group is about 5% of the model's explanation).")

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
    st.caption("Replays forecasts on the two held-out test seasons, which the models never saw, so each forecast can be "
               "compared with what actually happened.")
    today = s[s.date == date].set_index("city")
    t0 = today.time_utc.max()
    f_all = load_fires()
    fires_r = f_all[(f_all.hour_utc > t0 - pd.Timedelta(hours=72)) & (f_all.hour_utc <= t0)]
    forecast_view(today, city_r, hourly, fires_r, advisories, key="replay", replay=True)

with tab_how:
    doc = (ROOT / "docs" / "DATA_PIPELINE.md").read_text(encoding="utf-8")
    doc = re.sub(r"```mermaid.*?```", "**Flow:** APIs → `data/raw/` (untouched responses) → `data/interim/` (one table per source) → "
                 "notebook 02, nine cleaning steps → `data/processed/` (master table + CSVs) and the Data Quality Report", doc, flags=re.S)
    doc = re.sub(r"\]\(\.\./", "](https://github.com/FarhanRajputFelix/saans/blob/main/", doc)  # links point at the repository
    st.markdown(doc)

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
        for kind, color, name in [(False, "#d95926", "Low-cost sensor"), (True, "#3987e5", "Reference monitor")]:
            k = sens[sens.is_monitor == kind]
            fig.add_trace(go.Scattergeo(lat=k.lat, lon=k.lon, mode="markers", name=f"{name} ({len(k)})",
                                        marker=dict(size=11 if kind else 7, color=color, line=dict(color="#0b0e14", width=1)),
                                        text=k.location + " · " + k.provider.fillna(""), hovertemplate="%{text}<extra></extra>"))
        fig.update_geos(lataxis_range=[23.8, 34.5], lonaxis_range=[66, 75.5], showcountries=True, countrycolor="#4a4f5c",
                        showland=True, landcolor="#161a22", showocean=True, oceancolor="#0f1724", showframe=False, bgcolor="rgba(0,0,0,0)",
                        resolution=50)
        style(fig, 480)
        fig.update_layout(title=dict(text="Where the PM2.5 sensors are: coverage clusters in a few neighbourhoods", x=0, font=dict(color=INK)),
                          margin=dict(l=0, r=0, t=40, b=0), legend=dict(orientation="h", y=-0.02))
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
    for name, title in [("ablation_fire_features.csv", "Do the fire features help? Same model with and without them (MAE, µg/m³)"),
                        ("shap_group_shares.csv", "How much of the forecast each driver group explains (mean |SHAP|, %)")]:
        p = REPORTS / name
        if p.exists():
            st.markdown(f"**{title}**")
            st.dataframe(pd.read_csv(p), hide_index=True, width="stretch")
    for fig_name in ["forecast_lahore_nov2024.png", "hazard_threshold_choice.png", "shap_groups.png", "shap_top_features.png"]:
        fp = REPORTS / "figures" / fig_name
        if fp.exists():
            st.image(str(fp))

with tab_about:
    st.markdown("""
**SAANS** (Smog Attribution And Nowcasting System). *Saans* means breath in Urdu.

* **Data:** OpenAQ v3 (PM2.5, PM10), NASA FIRMS (VIIRS and MODIS fires), Open-Meteo (ERA5 history; forecast API for the live mode), GDELT news headlines.
* **Models:** LightGBM regressors (next 24 h and 24-48 h, predicting the change from the last 24 hours), quantile models for the 80% range, a LightGBM hazard classifier; SHAP for attribution; fire features constrained so more fire never lowers a forecast.
* **Risk categories:** the six official US EPA AQI categories and colours, computed from the 24-hour mean PM2.5.
* **LLM:** Gemini (Groq fallback) extracts the event calendar from headlines and writes the bilingual advisories. It only rewords the model's numbers, and every number it writes is checked.
* **Limits:** attribution is statistical, not chemical; Faisalabad and Multan have sensors only from June 2025; the live mode depends on the APIs answering.

**Enable the live forecast on Streamlit Cloud:** app menu → Settings → Secrets, then paste (one per line, values in quotes):
```
OPENAQ_API_KEY = "your key"
FIRMS_MAP_KEY = "your key"
GEMINI_API_KEY = "your key"
GROQ_API_KEY = "your key"
```

Data Science course project, SZABIST University Karachi. Code and notebooks: github.com/FarhanRajputFelix/saans
""")
