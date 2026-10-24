"""SAANS dashboard: smog forecasts for five Pakistani cities, with the reasons behind them.

Runs from precomputed files in app/data (written by notebooks 05 and 06), so it needs no model
and no API key. Local run:  streamlit run app/streamlit_app.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from saans.aqi import BREAKPOINTS, HAZARDOUS_PM25, pm25_to_aqi, risk_level  # noqa: E402

DATA = ROOT / "app" / "data"
REPORTS = ROOT / "reports"

CITIES = {"lahore": ("Lahore", "لاہور", 31.5497, 74.3436), "faisalabad": ("Faisalabad", "فیصل آباد", 31.4504, 73.1350),
          "multan": ("Multan", "ملتان", 30.1575, 71.5249), "islamabad": ("Islamabad", "اسلام آباد", 33.6844, 73.0479),
          "karachi": ("Karachi", "کراچی", 24.8607, 67.0011)}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
RISK_ROLE = {"Green": "good", "Yellow": "warning", "Orange": "serious", "Red": "critical"}
RISK_ICON = {"Green": "●", "Yellow": "▲", "Orange": "◆", "Red": "■"}
RISK_SYMBOL = {"Green": "circle", "Yellow": "triangle-up", "Orange": "diamond", "Red": "square"}  # shape, not colour alone
DRIVERS = {"Recent pollution": "#2a78d6", "Weather": "#eb6834", "Upwind fires": "#1baf7a", "Calendar": "#eda100"}
DRIVERS_UR = {"Recent pollution": "حالیہ آلودگی", "Weather": "موسم اور ہوا کا جمود",
              "Upwind fires": "ہوا کے رخ پر فصلوں کی آگ", "Calendar": "موسم اور تہوار کا کیلنڈر"}
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"

st.set_page_config(page_title="SAANS smog forecast", page_icon="🌫️", layout="wide")


@st.cache_data
def load():
    daily = pd.read_parquet(DATA / "forecasts_daily.parquet")
    daily["date"] = daily.time_pkt.dt.tz_convert("Asia/Karachi").dt.date
    hourly = pd.read_parquet(DATA / "observed_hourly.parquet")
    hourly["time_pkt"] = hourly.time_utc.dt.tz_convert("Asia/Karachi")
    adv_path = DATA / "advisories.json"
    advisories = json.loads(adv_path.read_text(encoding="utf-8")) if adv_path.exists() else {}
    evaluation = json.loads((DATA / "evaluation.json").read_text())
    return daily, hourly, advisories, evaluation


daily, hourly, advisories, evaluation = load()


def template_advisory(city: str, row) -> dict:
    """Rule-based fallback when no cached LLM advisory exists for this city and day."""
    name, name_ur = CITIES[city][0], CITIES[city][1]
    f = row.forecast_24h
    aqi = int(pm25_to_aqi(f))
    level = risk_level(f)[0]
    category = next((c for lo, hi, a, b, c in BREAKPOINTS if f <= hi + 0.05), "Hazardous")
    groups = sorted(DRIVERS, key=lambda g: row[f"shap_{g}"], reverse=True)[:2]
    advice_en = {"Green": "Air is acceptable; normal outdoor activity is fine.",
                 "Yellow": "Children, the elderly and people with asthma should cut long outdoor activity.",
                 "Orange": "Everyone should limit time outdoors and wear a mask when outside.",
                 "Red": "Hazardous smog: stay indoors, keep windows shut and use an N95 mask if you must go out."}[level]
    advice_ur = {"Green": "ہوا کا معیار قابلِ قبول ہے، معمول کی سرگرمیاں جاری رکھیں۔",
                 "Yellow": "بچے، بزرگ اور دمہ کے مریض طویل بیرونی سرگرمیاں کم کریں۔",
                 "Orange": "سب لوگ باہر کم وقت گزاریں اور باہر نکلتے وقت ماسک پہنیں۔",
                 "Red": "خطرناک سموگ: گھر کے اندر رہیں، کھڑکیاں بند رکھیں اور باہر جانا ضروری ہو تو N95 ماسک پہنیں۔"}[level]
    return {"source": "template",
            "en": f"{name}: the next 24 hours are forecast to average {f:.0f} µg/m³ of PM2.5 (AQI {aqi}, {category}). "
                  f"Main drivers: {groups[0].lower()} and {groups[1].lower()}. {advice_en}",
            "ur": f"{name_ur} میں آئندہ 24 گھنٹوں کے دوران PM2.5 کی اوسط سطح {f:.0f} مائیکروگرام فی مکعب میٹر (AQI {aqi}) متوقع ہے۔ "
                  f"بڑی وجوہات: {DRIVERS_UR[groups[0]]} اور {DRIVERS_UR[groups[1]]}۔ {advice_ur}"}


def badge(level: str) -> str:
    return f"<span style='color:{STATUS[RISK_ROLE[level]]};font-size:1.1em'>{RISK_ICON[level]}</span> <b>{level}</b>"


# ---------------- header & controls ----------------
st.markdown("## SAANS · Smog forecast for Pakistan's cities, and why")
st.caption("Forecasts of 24-hour mean PM2.5 issued at 08:00 Pakistan time, replayed over the two held-out test seasons. "
           "Built from OpenAQ sensors, NASA FIRMS fires, ERA5 weather and an LLM news calendar.")

c1, c2, c3 = st.columns([1, 1, 2])
season = c1.selectbox("Smog season", ["2024-25", "2025-26"], index=0)
s = daily[daily.season == season]
cities_here = [c for c in CITIES if c in set(s.city)]
city = c2.selectbox("City", cities_here, format_func=lambda c: CITIES[c][0],
                    index=cities_here.index("lahore") if "lahore" in cities_here else 0)
dates = sorted(s[s.city == city].date.unique())
default = pd.Timestamp("2024-11-06").date() if season == "2024-25" else dates[len(dates) // 2]
date = c3.select_slider("Forecast date (issued 08:00)", options=dates, value=default if default in dates else dates[0],
                        format_func=lambda d: pd.Timestamp(d).strftime("%a %d %b %Y"))

today = s[s.date == date].set_index("city")
row = today.loc[city]

tab_fc, tab_dq, tab_perf, tab_about = st.tabs(["Forecast", "Data quality", "Model performance", "About"])

with tab_fc:
    # ---------- city tiles + map ----------
    tiles = st.columns(len(today))
    for col, (c, r) in zip(tiles, today.iterrows()):
        level = r.risk_level
        col.markdown(f"**{CITIES[c][0]}**<br><span style='font-size:1.6em'>{r.forecast_24h:.0f}</span> µg/m³<br>"
                     f"AQI {int(pm25_to_aqi(r.forecast_24h))} · {badge(level)}<br>"
                     f"<span style='color:{INK_2};font-size:0.9em'>Chance of AQI &gt; 300: {r.hazard_prob:.0%}</span>",
                     unsafe_allow_html=True)

    left, right = st.columns([1, 1.4])
    with left:
        # Scattergeo draws its own borders: no WebGL, no tile server, works offline (safe for a live demo)
        fig = go.Figure()
        for level in ["Green", "Yellow", "Orange", "Red"]:
            sub = today[today.risk_level == level]
            fig.add_trace(go.Scattergeo(
                lat=[CITIES[c][2] for c in sub.index], lon=[CITIES[c][3] for c in sub.index], mode="markers+text",
                marker=dict(size=20, color=STATUS[RISK_ROLE[level]], symbol=RISK_SYMBOL[level], line=dict(color="#ffffff", width=2)),
                name=f"{level}", text=[CITIES[c][0] for c in sub.index], textposition="middle right",
                textfont=dict(color=INK, size=13),
                customdata=np.stack([sub.forecast_24h.round(0), [int(pm25_to_aqi(v)) for v in sub.forecast_24h]], axis=-1) if len(sub) else None,
                hovertemplate="<b>%{text}</b><br>Next 24 h: %{customdata[0]} µg/m³<br>AQI %{customdata[1]}<extra></extra>"))
        fig.update_geos(lataxis_range=[23.5, 35.5], lonaxis_range=[64, 78.5], showcountries=True, countrycolor="#c3c2b7",
                        showcoastlines=True, coastlinecolor="#c3c2b7", showland=True, landcolor="#f3f2ee",
                        showocean=True, oceancolor="#e8f0fa", showframe=False, resolution=50)
        fig.update_layout(margin=dict(l=0, r=0, t=30, b=0), height=430, title=dict(text="Forecast risk, next 24 hours", x=0),
                          legend=dict(orientation="h", y=-0.02, x=0), paper_bgcolor="#fcfcfb")
        st.plotly_chart(fig, width="stretch")

    # ---------- 48 h chart ----------
    with right:
        t0 = row.time_pkt.tz_convert("Asia/Karachi")
        obs = hourly[(hourly.city == city) & (hourly.time_pkt > t0 - pd.Timedelta(days=5)) & (hourly.time_pkt <= t0 + pd.Timedelta(hours=48))]
        past, future = obs[obs.time_pkt <= t0], obs[obs.time_pkt > t0]
        d1, d2 = t0 + pd.Timedelta(hours=24), t0 + pd.Timedelta(hours=48)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=past.time_pkt, y=past.pm25, mode="lines", name="Observed (hourly)",
                                 line=dict(color=INK, width=1.6), hovertemplate="%{x|%d %b %H:%M}: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=future.time_pkt, y=future.pm25, mode="lines", name="What actually happened",
                                 line=dict(color=MUTED, width=1.2, dash="dot"), hovertemplate="%{x|%d %b %H:%M}: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=[t0, d1, d1, t0], y=[row.q10, row.q10, row.q90, row.q90], fill="toself", mode="none",
                                 fillcolor="rgba(42,120,214,0.15)", name="80% range (next 24 h)", hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=[t0, d1], y=[row.forecast_24h] * 2, mode="lines", name="Forecast: next 24 h",
                                 line=dict(color="#2a78d6", width=3), hovertemplate="Next 24 h mean: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_trace(go.Scatter(x=[d1, d2], y=[row.forecast_48h] * 2, mode="lines", name="Forecast: 24-48 h",
                                 line=dict(color="#2a78d6", width=3, dash="dash"), hovertemplate="24-48 h mean: %{y:.0f} µg/m³<extra></extra>"))
        fig.add_hline(y=HAZARDOUS_PM25, line=dict(color=STATUS["critical"], width=1, dash="dot"),
                      annotation_text="Hazardous (AQI 300)", annotation_position="top left", annotation_font_color=INK_2)
        fig.add_vline(x=t0, line=dict(color=MUTED, width=1))
        fig.update_layout(title=dict(text=f"{CITIES[city][0]}: last 5 days and the 48-hour forecast", x=0), height=430,
                          margin=dict(l=10, r=10, t=40, b=10), plot_bgcolor="#fcfcfb", hovermode="x unified",
                          yaxis=dict(title="PM2.5 (µg/m³)", gridcolor=GRID, rangemode="tozero"), xaxis=dict(gridcolor=GRID),
                          legend=dict(orientation="h", y=-0.15, x=0, font=dict(size=11)))
        st.plotly_chart(fig, width="stretch")

    # ---------- why today + what-if ----------
    why, whatif = st.columns([1.2, 1])
    with why:
        st.markdown("#### Why this forecast?")
        groups = list(DRIVERS)
        vals = [row[f"shap_{g}"] for g in groups]
        order = np.argsort(vals)
        fig = go.Figure(go.Bar(x=[vals[i] for i in order], y=[groups[i] for i in order], orientation="h",
                               marker=dict(color=[DRIVERS[groups[i]] for i in order]),
                               text=[f"{vals[i]:+.0f}" for i in order], textposition="outside",
                               hovertemplate="%{y}: %{x:+.0f} µg/m³<extra></extra>"))
        fig.update_layout(height=250, margin=dict(l=10, r=40, t=10, b=10), plot_bgcolor="#fcfcfb",
                          xaxis=dict(title="µg/m³ above or below the typical level", gridcolor=GRID, zeroline=True, zerolinecolor="#c3c2b7"))
        st.plotly_chart(fig, width="stretch")
        top = json.loads(row.top_drivers)
        st.caption(f"Typical level {row.shap_base:.0f} µg/m³ + driver contributions = {row.forecast_24h:.0f} µg/m³. "
                   "Strongest single factors: " + "; ".join(f"{d['label']} ({d['ug_m3']:+.0f})" for d in top) +
                   ". SHAP shows what the model relied on, which is statistical, not a chemical source measurement.")
    with whatif:
        st.markdown("#### What if there were fewer crop fires?")
        cut = st.slider("Reduce upwind crop fires by", 0, 100, 0, step=10, format="%d%%")
        new = row[f"whatif_{cut}"]
        st.metric("Forecast, next 24 h", f"{new:.0f} µg/m³",
                  delta=f"{new - row.forecast_24h:+.0f} µg/m³ vs actual fire levels" if cut else None, delta_color="inverse")
        st.caption(f"AQI {int(pm25_to_aqi(new))}, {risk_level(new)[0]}. A model-based estimate: the fire features are scaled down "
                   "and the forecast recomputed, holding everything else fixed.")

    # ---------- advisory ----------
    st.markdown("#### Health advisory · صحت سے متعلق ہدایات")
    key = f"{city}|{date}"
    adv = advisories.get(key) or template_advisory(city, row)
    src = "AI Smog Explainer (LLM, numbers taken from the model)" if adv.get("source") != "template" else "Rule-based template (no LLM advisory cached for this day)"
    a1, a2 = st.columns(2)
    a1.info(adv["en"])
    a2.markdown(f"<div dir='rtl' style='background:#eef5fd;padding:12px 16px;border-radius:8px;font-size:1.1em;line-height:1.9'>{adv['ur']}</div>",
                unsafe_allow_html=True)
    st.caption(f"Source: {src}.")
    if pd.notna(row.target_24h):
        st.caption(f"Replay check: the next 24 hours actually averaged {row.target_24h:.0f} µg/m³ (AQI {int(pm25_to_aqi(row.target_24h))}).")

with tab_dq:
    st.markdown("Cleaning is the core of the project: nine steps, every one logged with before and after counts "
                "(notebook 02).")
    p = REPORTS / "data_quality_report.md"
    if p.exists():
        st.markdown(p.read_text(encoding="utf-8").split("\n", 2)[-1])
    for fig_name, cap in [("sensor_coverage.png", "Sensor coverage per city"), ("blh_imputation_check.png", "Boundary layer height imputation check")]:
        fp = REPORTS / "figures" / fig_name
        if fp.exists():
            st.image(str(fp), caption=cap)

with tab_perf:
    st.markdown("Trained on 2020 to Sep 2024; tested on the 2024-25 and 2025-26 smog seasons. "
                "Skill = 1 - MAE(model) / MAE(persistence); above 0 beats persistence.")
    reg = pd.DataFrame(evaluation["regression"])
    st.markdown("**24-hour mean PM2.5 forecasts (MAE in µg/m³)**")
    st.dataframe(reg, hide_index=True, width="stretch")
    st.markdown("**Hazard warnings (next 24 h above AQI 300)**")
    st.dataframe(pd.DataFrame(evaluation["classifier"]), hide_index=True, width="stretch")
    for fig_name in ["forecast_lahore_nov2024.png", "shap_groups.png"]:
        fp = REPORTS / "figures" / fig_name
        if fp.exists():
            st.image(str(fp))

with tab_about:
    st.markdown("""
**SAANS** (Smog Attribution And Nowcasting System). *Saans* means breath in Urdu.

* **Data:** OpenAQ v3 (PM2.5), NASA FIRMS (VIIRS and MODIS fires), Open-Meteo ERA5 (hourly weather), GDELT news headlines.
* **Models:** LightGBM regressors (24 h and 48 h), quantile models for the 80% range, a LightGBM hazard classifier; SHAP for attribution.
* **LLM:** Gemini (Groq fallback) extracts the event calendar from headlines and writes the bilingual advisories. It only rewords the model's numbers.
* **Limits:** attribution is statistical, not chemical; ERA5 is a ~25 km grid; Faisalabad and Multan have sensors only from June 2025.

Data Science course project, SZABIST University Karachi. Code: github.com/FarhanRajputFelix/saans
""")
