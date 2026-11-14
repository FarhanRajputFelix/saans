"""Write the SAANS Power BI project (PBIP): a semantic model that loads powerbi/data/*.csv from GitHub, and a
six-page report that mirrors the Streamlit dashboard. Open powerbi/SAANS.pbip in Power BI Desktop and click Refresh.

Run from the repository root after export_data.py:  python powerbi/build_pbip.py
"""
import json
import os
import shutil
import uuid
from pathlib import Path

import pandas as pd

from make_basemap import LAT0, LAT1, LON0, LON1

HERE = Path(__file__).parent
DATA = HERE / "data"
NAME = "SAANS"
# where Power BI loads the tables from; SAANS_DATA_URL overrides it (e.g. a local test server)
BASE_URL = os.environ.get("SAANS_DATA_URL", "https://raw.githubusercontent.com/FarhanRajputFelix/saans/main/")

# ---------------------------------------------------------------- colours (same tokens as the web dashboard)
BG, SURFACE, SURFACE_2, BORDER = "#0b0e14", "#161a22", "#1b2029", "#2a2f3a"
INK, INK_2, MUTED, ACCENT = "#f0efec", "#c3c2b7", "#898781", "#3987e5"
EPA = {"Good": "#00e400", "Moderate": "#ffff00", "Unhealthy for Sensitive Groups": "#ff7e00", "Unhealthy": "#ff0000",
       "Very Unhealthy": "#8f3f97", "Hazardous": "#7e0023"}
DRIVERS = {"Recent pollution": "#2a78d6", "Weather": "#eb6834", "Upwind fires": "#1baf7a", "Calendar": "#eda100"}
FIRE = "#f2a541"

# ---------------------------------------------------------------- semantic model
# table name -> (source csv relative to the repository root, column types that are not inferred, key columns)
TABLES = {
    "Forecasts": ("powerbi/data/forecasts.csv", {"date": "date", "issued_pkt": "dateTime"}),
    "Issues": ("powerbi/data/issues.csv", {"date": "date", "issued_pkt": "dateTime"}),
    "Cities": ("powerbi/data/cities.csv", {}),
    "Drivers": ("powerbi/data/drivers.csv", {}),
    "WhatIf": ("powerbi/data/whatif.csv", {}),
    "Chart": ("powerbi/data/chart_hourly.csv", {"time_pkt": "dateTime"}),
    "MapPoints": ("powerbi/data/map_points.csv", {}),
    "Categories": ("powerbi/data/categories.csv", {}),
    "Model accuracy": ("powerbi/data/evaluation_regression.csv", {}),
    "Hazard warnings": ("powerbi/data/evaluation_classifier.csv", {}),
    "Fire ablation": ("powerbi/data/ablation_fire_features.csv", {}),
    "SHAP shares": ("powerbi/data/shap_group_shares.csv", {}),
    "Data received": ("powerbi/data/dq_totals.csv", {}),
    "Cleaning steps": ("powerbi/data/dq_cleaning_steps.csv", {}),
    "Sensors": ("powerbi/data/dq_sensors.csv", {}),
    "Raw records": ("powerbi/data/dq_raw_records.csv", {}),
    "Sensor map": ("powerbi/data/dq_sensor_map.csv", {}),
    "Live status": ("powerbi/data/live_status.csv", {"run_pkt": "dateTime"}),
}
CLEANED_COLS = ["city", "time_pkt", "pm25", "pm25_source", "pm25_interpolated", "long_gap", "pm10", "temperature_2m",
                "relative_humidity_2m", "wind_speed_10m", "wind_direction_10m", "boundary_layer_height", "blh_imputed",
                "precipitation", "fires_300km", "is_test_season", "extreme_event", "fireworks_night"]
# display formats for numeric columns shown in the report's tables
FORMATS = {"skill_vs_persistence": "+0.0%;-0.0%;0.0%", "hit_rate": "0.0%", "false_alarm_ratio": "0.0%", "false_alarm_rate": "0.0%",
           "F1": "0.000", "MAE_model": "0.0", "MAE_persistence": "0.0", "MAE_seasonal": "0.0", "RMSE_model": "0.0", "RMSE_persistence": "0.0",
           "mean_pm25": "0", "hours": "#,0", "hazardous_hours": "#,0", "MAE_with_fires": "0.00", "MAE_without_fires": "0.00",
           "RMSE_with_fires": "0.00", "RMSE_without_fires": "0.00", "MAE_change_from_fires": "+0.00;-0.00;0.00",
           "received": "#,0", "after_cleaning": "#,0", "share_kept": "0.0", "rows_before": "#,0", "rows_after": "#,0", "removed": "#,0",
           "sensors_received": "#,0", "sensors_kept": "#,0", "sensors_rejected": "#,0", "hours_received": "#,0", "hours_kept": "#,0",
           "raw_records": "#,0", "percent": "0.0", "forecast_24h": "0", "forecast_48h": "0", "last_24h": "0", "aqi": "0",
           "pm25": "0", "pm10": "0", "temperature_2m": "0.0", "relative_humidity_2m": "0", "wind_speed_10m": "0.0",
           "boundary_layer_height": "#,0", "fires_300km": "#,0"}
M_TYPE = {"string": "type text", "double": "type number", "int64": "Int64.Type", "dateTime": "type datetime", "date": "type date"}

MEASURES = {
    "Forecasts": [
        ("Forecast next 24 h", "AVERAGE(Forecasts[forecast_24h])", "0"),
        ("Forecast 24-48 h", "AVERAGE(Forecasts[forecast_48h])", "0"),
        ("Last 24 h", "AVERAGE(Forecasts[last_24h])", "0"),
        ("AQI next 24 h", "AVERAGE(Forecasts[aqi])", "0"),
        ("Risk level", "SELECTEDVALUE(Forecasts[category_short])", None),
        ("Category colour", "SELECTEDVALUE(Forecasts[category_color], \"" + SURFACE_2 + "\")", None),
        ("Category text colour", "SELECTEDVALUE(Forecasts[category_text_color], \"" + INK + "\")", None),
        ("Chance AQI above 300", "AVERAGE(Forecasts[hazard_prob])", "0%"),
        ("80% range", "IF(HASONEVALUE(Forecasts[forecast_id]), FORMAT(AVERAGE(Forecasts[q10]), \"0\") & \" to \" & "
                      "FORMAT(AVERAGE(Forecasts[q90]), \"0\") & \" µg/m³\")", None),
        ("Typical level", "AVERAGE(Forecasts[typical_level])", "0"),
        ("Observed next 24 h", "AVERAGE(Forecasts[observed_next_24h])", "0"),
        ("City headline", "IF(HASONEVALUE(Forecasts[forecast_id]), SELECTEDVALUE(Cities[City]) & \": \" & FORMAT([Forecast next 24 h], \"0\") & "
                          "\" µg/m³ next 24 h · US EPA AQI \" & FORMAT([AQI next 24 h], \"0\") & \" · \" & [Risk level] & \" · chance of AQI > 300: \" & "
                          "FORMAT([Chance AQI above 300], \"0%\"), \"Select one city\")", None),
        ("Forecast details", "IF(HASONEVALUE(Forecasts[forecast_id]), \"80% range \" & [80% range] & \" · last 24 h \" & FORMAT([Last 24 h], \"0\") & "
                             "\" · the 24 hours after that: \" & FORMAT([Forecast 24-48 h], \"0\") & \" µg/m³ (\" & SELECTEDVALUE(Forecasts[f48_category]) & \")\")", None),
        ("Why caption", "IF(HASONEVALUE(Forecasts[forecast_id]), \"Typical level \" & FORMAT([Typical level], \"0\") & \" µg/m³ + driver contributions = \" & "
                        "FORMAT([Forecast next 24 h], \"0\") & \" µg/m³. Strongest single factors: \" & SELECTEDVALUE(Forecasts[top_drivers]) & "
                        "\". SHAP shows what the model relied on: statistical, not a chemical source measurement.\")", None),
        ("Replay check", "IF(HASONEVALUE(Forecasts[forecast_id]), IF(ISBLANK([Observed next 24 h]), \"No complete observation for the next 24 hours.\", "
                         "\"What actually happened: the next 24 hours averaged \" & FORMAT([Observed next 24 h], \"0\") & \" µg/m³ (AQI \" & "
                         "FORMAT(AVERAGE(Forecasts[observed_aqi]), \"0\") & \", \" & SELECTEDVALUE(Forecasts[observed_category]) & \"). Forecast error: \" & "
                         "FORMAT([Forecast next 24 h] - [Observed next 24 h], \"+0;-0;0\") & \" µg/m³.\"))", None),
        ("Advisory English", "SELECTEDVALUE(Forecasts[advisory_english])", None),
        ("Advisory Urdu", "SELECTEDVALUE(Forecasts[advisory_urdu])", None),
        ("Advisory source", "IF(HASONEVALUE(Forecasts[forecast_id]), \"Source: \" & SELECTEDVALUE(Forecasts[advisory_source]))", None),
        ("Mean absolute error", "AVERAGEX(FILTER(Forecasts, NOT ISBLANK(Forecasts[error_24h])), ABS(Forecasts[error_24h]))", "0.0"),
    ],
    "Issues": [
        ("Issued", "\"Issued \" & FORMAT(MAX(Issues[issued_pkt]), \"ddd d mmm yyyy, HH:mm\") & \" PKT\"", None),
    ],
    "Live status": [
        ("Live status text", "\"Latest live snapshot: run \" & FORMAT(MAX('Live status'[run_pkt]), \"d mmm yyyy, HH:mm\") & \" PKT · \" & "
                             "FORMAT(SUM('Live status'[sensors_reporting]), \"0\") & \" sensors across 5 cities · \" & MAX('Live status'[fire_data]) & "
                             "\". Refresh this report to load the newest snapshot from GitHub.\"", None),
    ],
    "Drivers": [("Driver contribution", "SUM(Drivers[ug_m3])", "+0;-0;0")],
    "Chart": [
        ("Observed (hourly)", "AVERAGE(Chart[observed])", "0"),
        ("What actually happened", "AVERAGE(Chart[actual_after])", "0"),
        ("Forecast (next 48 h)", "AVERAGE(Chart[forecast])", "0"),
        ("80% range low", "AVERAGE(Chart[band_low])", "0"),
        ("80% range high", "AVERAGE(Chart[band_high])", "0"),
        ("Hazardous (AQI 300)", "IF(NOT ISEMPTY(Chart), 225.5)", "0"),
    ],
    "WhatIf": [
        ("What-if forecast", "VAR r = [Fire reduction value] RETURN CALCULATE(AVERAGE(WhatIf[forecast_ug_m3]), WhatIf[fire_reduction_pct] = r)", "0"),
        ("What-if AQI", "VAR r = [Fire reduction value] RETURN CALCULATE(AVERAGE(WhatIf[aqi]), WhatIf[fire_reduction_pct] = r)", "0"),
        ("What-if text", "VAR r = [Fire reduction value] VAR f = [What-if forecast] RETURN IF(HASONEVALUE(Forecasts[forecast_id]), "
                         "\"With \" & r & \"% fewer upwind crop fires: \" & FORMAT(f, \"0\") & \" µg/m³, AQI \" & FORMAT([What-if AQI], \"0\") & \" (\" & "
                         "CALCULATE(SELECTEDVALUE(WhatIf[category]), WhatIf[fire_reduction_pct] = r) & \"), \" & "
                         "FORMAT(f - [Forecast next 24 h], \"+0;-0;0\") & \" µg/m³ against the forecast. A model-based estimate: fire features are \" & "
                         "\"scaled down and the forecast recomputed, everything else fixed; fewer fires can never raise a forecast.\")", None),
        ("What-if colour", "VAR r = [Fire reduction value] RETURN CALCULATE(SELECTEDVALUE(WhatIf[category_color], \"" + SURFACE_2 + "\"), "
                           "WhatIf[fire_reduction_pct] = r)", None),
    ],
    "Model accuracy": [("Skill vs persistence", "AVERAGE('Model accuracy'[skill_vs_persistence])", "+0.0%;-0.0%;0.0%")],
}


def model_table(name, path, overrides):
    if path:
        sample = pd.read_csv(HERE.parent / path, nrows=2000)
        cols = {}
        for c, t in sample.dtypes.items():
            cols[c] = overrides.get(c) or ("double" if t.kind == "f" else "int64" if t.kind in "iu" else "string")
    columns = []
    for c, t in cols.items():
        col = {"name": c, "dataType": "dateTime" if t == "date" else t, "sourceColumn": c, "summarizeBy": "none" if t in ("string", "date", "dateTime") else "sum"}
        if c in ("latitude", "lat"):
            col.update(dataCategory="Latitude", summarizeBy="none")
        if c in ("longitude", "lon"):
            col.update(dataCategory="Longitude", summarizeBy="none")
        if c.endswith(("_id", "_key", "_order", "order", "_pct", "step")) or c in ("hours_from_issue",):
            col["summarizeBy"] = "none"
        fmt = FORMATS.get(c)
        if fmt and t in ("double", "int64"):
            col["formatString"] = fmt
        if t == "dateTime":
            col["formatString"] = "d mmm yyyy HH:mm"
        if t == "date":
            col["formatString"] = "d mmm yyyy"
        columns.append(col)
    types = ", ".join(f'{{"{c}", {M_TYPE[t]}}}' for c, t in cols.items())
    m = ["let",
         f'    Source = Csv.Document(Web.Contents("{BASE_URL}", [RelativePath = "{path}"]), [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),',
         "    Headers = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),",
         f'    Typed = Table.TransformColumnTypes(Headers, {{{types}}}, "en-US")',
         "in", "    Typed"]
    table = {"name": name, "columns": columns,
             "partitions": [{"name": name, "mode": "import", "source": {"type": "m", "expression": m}}],
             "annotations": [{"name": "PBI_ResultType", "value": "Table"}]}
    ms = [{"name": n, "expression": e, **({"formatString": f} if f else {})} for n, e, f in MEASURES.get(name, [])]
    if ms:
        table["measures"] = ms
    return table


def cleaned_table():
    sample = pd.read_csv(HERE.parent / "data/processed/csv/master_hourly_lahore.csv", nrows=2000, usecols=CLEANED_COLS)
    cols = {c: "dateTime" if c == "time_pkt" else "double" if sample[c].dtype.kind in "fi" and c != "city" else "string"
            for c in CLEANED_COLS}
    cols["date"] = "date"
    columns = [{"name": c, "dataType": "dateTime" if t == "date" else t, "sourceColumn": c, "summarizeBy": "none" if t != "double" else "sum",
                **({"formatString": "d mmm yyyy HH:mm"} if t == "dateTime" else {"formatString": "d mmm yyyy"} if t == "date"
                   else {"formatString": FORMATS[c]} if c in FORMATS else {})}
               for c, t in cols.items()]
    # five plain reads combined (no function or list of URLs, so Power Query sees one static source)
    cities = ["lahore", "faisalabad", "multan", "islamabad", "karachi"]
    pick = "{" + ", ".join(json.dumps(c) for c in CLEANED_COLS) + "}"
    types = ", ".join(f'{{"{c}", {M_TYPE[t]}}}' for c, t in cols.items() if c != "date")
    m = ["let"]
    for c in cities:
        m.append(f'    {c} = Table.SelectColumns(Table.PromoteHeaders(Csv.Document(Web.Contents("{BASE_URL}", [RelativePath = "data/processed/csv/master_hourly_{c}.csv"]), '
                 f'[Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]), [PromoteAllScalars = true]), {pick}),')
    m += [f"    Combined = Table.Combine({{{', '.join(cities)}}}),",
          f'    Typed = Table.TransformColumnTypes(Combined, {{{types}}}, "en-US"),',
          '    Proper = Table.TransformColumns(Typed, {{"city", Text.Proper, type text}}),',
          '    WithDate = Table.AddColumn(Proper, "date", each DateTime.Date([time_pkt]), type date)',
          "in", "    WithDate"]
    return {"name": "Cleaned hourly", "columns": columns,
            "partitions": [{"name": "Cleaned hourly", "mode": "import", "source": {"type": "m", "expression": m}}],
            "measures": [{"name": "Average PM2.5", "expression": "AVERAGE('Cleaned hourly'[pm25])", "formatString": "0"}],
            "annotations": [{"name": "PBI_ResultType", "value": "Table"}]}


def semantic_model():
    tables = [model_table(n, p, o) for n, (p, o) in TABLES.items()] + [cleaned_table()]
    # what-if parameter: share of upwind fires removed
    tables.append({"name": "Fire reduction",
                   "columns": [{"name": "Fire reduction", "dataType": "int64", "sourceColumn": "[Value]", "type": "calculatedTableColumn",
                                "isNameInferred": False, "formatString": "0\\%", "summarizeBy": "none",
                                "extendedProperties": [{"type": "json", "name": "ParameterMetadata", "value": {"version": 0}}]}],
                   "partitions": [{"name": "Fire reduction", "mode": "import", "source": {"type": "calculated", "expression": "GENERATESERIES(0, 100, 10)"}}],
                   "measures": [{"name": "Fire reduction value", "expression": "SELECTEDVALUE('Fire reduction'[Fire reduction], 0)", "formatString": "0"}]})
    by = {t["name"]: t for t in tables}
    # names are case-insensitive in a Power BI model: no column may share a name with another column or a measure
    all_measures = [m["name"].lower() for t in tables for m in t.get("measures", [])]
    assert len(all_measures) == len(set(all_measures)), "duplicate measure names"
    for t in tables:
        names = [c["name"].lower() for c in t["columns"]] + [m["name"].lower() for m in t.get("measures", [])]
        assert len(names) == len(set(names)), (t["name"], sorted(n for n in names if names.count(n) > 1))
    for c in by["Cities"]["columns"]:  # cities in the dashboard's order, not alphabetical
        if c["name"] == "City":
            c["sortByColumn"] = "order"
    by["Cities"]["columns"].append({"name": "order", "dataType": "int64", "type": "calculated", "summarizeBy": "none", "isHidden": True,
                                    "expression": "SWITCH(Cities[city_key], \"lahore\", 1, \"faisalabad\", 2, \"multan\", 3, \"islamabad\", 4, 5)"})
    rels = [("Forecasts", "issue_key", "Issues", "issue_key"), ("Forecasts", "city", "Cities", "city_key"),
            ("Drivers", "forecast_id", "Forecasts", "forecast_id"), ("WhatIf", "forecast_id", "Forecasts", "forecast_id"),
            ("Chart", "forecast_id", "Forecasts", "forecast_id"), ("MapPoints", "issue_key", "Issues", "issue_key")]
    model = {
        "name": NAME,
        "compatibilityLevel": 1567,
        "model": {
            "culture": "en-US",
            # every source is the project's public GitHub data, so this file ignores privacy levels (no prompt on refresh)
            "dataAccessOptions": {"fastCombine": True, "legacyRedirects": True, "returnErrorValuesAsNull": True},
            "defaultPowerBIDataSourceVersion": "powerBI_V3",
            "sourceQueryCulture": "en-US",
            "tables": tables,
            "relationships": [{"name": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{a}.{b}->{c}.{d}")), "fromTable": a, "fromColumn": b,
                               "toTable": c, "toColumn": d} for a, b, c, d in rels],
            "annotations": [{"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
                            {"name": "PBI_QueryOrder", "value": json.dumps([t["name"] for t in tables if t["name"] != "Fire reduction"])}],
        },
    }
    return model


# ---------------------------------------------------------------- report helpers
def lit(v):
    if isinstance(v, bool):
        return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
    if isinstance(v, (int, float)):
        return {"expr": {"Literal": {"Value": f"{v}D"}}}
    return {"expr": {"Literal": {"Value": "'" + str(v).replace("'", "''") + "'"}}}


def color(c):
    return {"solid": {"color": lit(c)}}


def measure_color(entity, measure):
    return {"solid": {"color": {"expr": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": measure}}}}}


def props(**kw):
    return [{"properties": {k: v if isinstance(v, dict) and ("expr" in v or "solid" in v) else lit(v) for k, v in kw.items()}}]


class Query:
    """Builds a visual's prototypeQuery and the queryRefs its projections point at."""

    def __init__(self):
        self.sources, self.select, self.order = {}, [], []

    def _src(self, entity):
        if entity not in self.sources:
            self.sources[entity] = f"t{len(self.sources)}"
        return {"SourceRef": {"Source": self.sources[entity]}}

    def col(self, entity, prop):
        ref = f"{entity}.{prop}"
        self.select.append({"Column": {"Expression": self._src(entity), "Property": prop}, "Name": ref})
        return ref

    def measure(self, entity, prop):
        ref = f"{entity}.{prop}"
        self.select.append({"Measure": {"Expression": self._src(entity), "Property": prop}, "Name": ref})
        return ref

    def agg(self, entity, prop, fn=0):
        names = {0: "Sum", 1: "Avg", 3: "Min", 4: "Max"}
        ref = f"{names[fn]}({entity}.{prop})"
        self.select.append({"Aggregation": {"Expression": {"Column": {"Expression": self._src(entity), "Property": prop}}, "Function": fn},
                            "Name": ref})
        return ref

    def sort(self, entity, prop, descending=False, kind="Column"):
        self.order.append({"Direction": 2 if descending else 1, "Expression": {kind: {"Expression": self._src(entity), "Property": prop}}})

    def proto(self):
        q = {"Version": 2, "From": [{"Name": a, "Entity": e, "Type": 0} for e, a in self.sources.items()], "Select": self.select}
        if self.order:
            q["OrderBy"] = self.order
        return q


def in_filter(entity, prop, values, name=None):
    """A categorical filter: entity[prop] in values (used for page filters, visual filters and saved slicer selections)."""
    src = {"Name": "f", "Entity": entity, "Type": 0}
    def one(v):
        if isinstance(v, str) and v.startswith("datetime'"):
            return {"Literal": {"Value": v}}
        return {"Literal": {"Value": f"{v}L"}} if isinstance(v, (int, float)) else lit(v)["expr"]
    vals = [[one(v)] for v in values]
    flt = {"Version": 2, "From": [src],
           "Where": [{"Condition": {"In": {"Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": prop}}],
                                           "Values": vals}}}]}
    return flt if name is None else {"name": name, "expression": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": prop}},
                                     "filter": flt, "type": "Categorical", "howCreated": 1, "isHiddenInViewMode": True}


class Page:
    def __init__(self, display, height=720, width=1280):
        self.display, self.height, self.width = display, height, width
        self.visuals, self.filters, self.no_filter = [], [], []
        self.name = "s" + uuid.uuid5(uuid.NAMESPACE_URL, display).hex[:18]

    def add(self, vtype, x, y, w, h, q=None, proj=None, objects=None, title=None, vc=None, col_props=None, filters=None, name=None):
        name = name or f"v{len(self.visuals)}_{uuid.uuid5(uuid.NAMESPACE_URL, self.display + str(len(self.visuals))).hex[:10]}"
        sv = {"visualType": vtype, "drillFilterOtherVisuals": True}
        if proj:
            sv["projections"] = {role: [{"queryRef": r, **({"active": True} if role in ("Category", "Values") and vtype != "tableEx" else {})}
                                        for r in refs] for role, refs in proj.items()}
        if q:
            sv["prototypeQuery"] = q.proto()
        if col_props:
            sv["columnProperties"] = {k: {"displayName": v} for k, v in col_props.items()}
        if objects:
            sv["objects"] = objects
        vco = {"background": props(show=True, color=color(SURFACE), transparency=0),
               "border": props(show=True, color=color(BORDER), radius=10),
               "dropShadow": props(show=False)}
        if title:
            vco["title"] = props(show=True, text=title, fontColor=color(INK), fontSize=12, bold=True)
        else:
            vco["title"] = props(show=False)
        if vc:
            vco.update(vc)
        sv["vcObjects"] = vco
        cfg = {"name": name, "layouts": [{"id": 0, "position": {"x": x, "y": y, "z": len(self.visuals) * 1000, "width": w, "height": h}}],
               "singleVisual": sv}
        self.visuals.append({"x": x, "y": y, "z": len(self.visuals) * 1000, "width": w, "height": h, "config": json.dumps(cfg),
                             "filters": json.dumps(filters or [])})
        return name

    # ---- building blocks
    def text(self, x, y, w, h, runs, background=False):
        """runs: list of paragraphs; each paragraph a list of (text, style dict) or (text, style, url)."""
        paragraphs = []
        for para in runs:
            tr = []
            for item in para:
                t, style = item[0], item[1]
                run = {"value": t, "textStyle": {"fontFamily": "Segoe UI", "color": INK, **style}}
                if len(item) > 2:
                    run["url"] = item[2]
                tr.append(run)
            paragraphs.append({"textRuns": tr})
        vc = {"background": props(show=background, color=color(SURFACE), transparency=0), "border": props(show=background, color=color(BORDER), radius=10)}
        return self.add("textbox", x, y, w, h, objects={"general": [{"properties": {"paragraphs": paragraphs}}]}, vc=vc)

    def card(self, x, y, w, h, entity, measure, label=None, size=22, value_color=None, back=None, text_color=None):
        q = Query()
        ref = q.measure(entity, measure)
        obj = {"labels": props(color=value_color or color(INK), fontSize=size), "categoryLabels": props(show=bool(label), color=color(MUTED), fontSize=10)}
        if text_color:
            obj["labels"] = props(color=text_color, fontSize=size)
        vc = {"background": props(show=True, color=back or color(SURFACE), transparency=0)} if back else None
        return self.add("card", x, y, w, h, q, {"Values": [ref]}, obj, title=None, vc=vc, col_props={ref: label} if label else None)

    def text_card(self, x, y, w, h, entity, measure, size=11, title=None, ink=INK, back=None):
        """A wrapping text panel for a text measure: a one-column table (the header is the label, the cell wraps)."""
        q = Query()
        ref = q.measure(entity, measure)
        obj = {"values": props(fontSize=size, fontColorPrimary=color(ink), backColorPrimary=color(SURFACE), wordWrap=True),
               "columnHeaders": props(show=bool(title), fontSize=10, fontColor=color(INK_2), backColor=color(SURFACE), autoSizeColumnWidth=False,
                                      bold=True),
               "columnWidth": [{"properties": {"value": lit(w - 30)}, "selector": {"metadata": ref}}],
               "grid": props(gridHorizontal=False, gridVertical=False, rowPadding=4, outlineColor=color(SURFACE)), "total": props(totals=False)}
        return self.add("tableEx", x, y, w, h, q, {"Values": [ref]}, obj, title=None, col_props={ref: title or " "})

    def slicer(self, x, y, w, h, entity, prop, mode="Dropdown", default=None, title=None, single=True, horizontal=False, name=None):
        q = Query()
        ref = q.col(entity, prop)
        obj = {"data": props(mode=mode), "selection": props(singleSelect=single, strictSingleSelect=single, selectAllCheckboxEnabled=False),
               "header": props(show=bool(title), text=title or "", fontColor=color(INK_2), textSize=10),
               "items": props(fontColor=color(INK), background=color(SURFACE_2), textSize=11)}
        if horizontal:
            obj["general"] = props(orientation=1)
        if default is not None:
            obj.setdefault("general", [{"properties": {}}])
            obj["general"][0]["properties"]["filter"] = {"filter": in_filter(entity, prop, [default])}
        return self.add("slicer", x, y, w, h, q, {"Values": [ref]}, obj, name=name)

    def section(self, ordinal):
        cfg = {"objects": {"background": props(color=color(BG), transparency=0), "outspace": props(color=color(BG), transparency=0)}}
        if self.no_filter:
            cfg["relationships"] = [{"source": s, "target": t, "type": 3} for s, t in self.no_filter]
        fit = 1 if os.environ.get("SAANS_FIT") else (2 if self.height > 720 else 1)
        return {"name": self.name, "displayName": self.display, "displayOption": fit, "width": self.width,
                "height": self.height, "ordinal": ordinal, "config": json.dumps(cfg), "filters": json.dumps(self.filters),
                "visualContainers": self.visuals}


def geo_map(p, x, y, w, h, entity, point, lat, lon, legend, colors, title, size=None, tooltip=None):
    """Points on the basemap: a scatter chart whose axes are pinned to the image's extent (works offline, no sign-in)."""
    q = Query()
    cat = q.col(entity, point)
    ser = q.col(entity, legend)
    xs, ys = q.agg(entity, lon, 1), q.agg(entity, lat, 1)
    proj = {"Category": [cat], "Series": [ser], "X": [xs], "Y": [ys]}
    if size:
        proj["Size"] = [q.agg(entity, size, 0)]
    if tooltip:
        proj["Tooltips"] = [q.col(entity, tooltip)]
    dp = [{"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0,
           "Left": {"Column": {"Expression": {"SourceRef": {"Entity": entity}}, "Property": legend}}, "Right": {"Literal": {"Value": f"'{k}'"}}}}}]}}
          for k, c in colors.items()]
    axis = dict(show=False, gridlineShow=False, showAxisTitle=False)
    obj = {"dataPoint": dp,
           "categoryAxis": props(start=LON0, end=LON1, **axis), "valueAxis": props(start=LAT0, end=LAT1, **axis),
           "legend": props(show=True, position="Bottom", labelColor=color(INK_2), fontSize=9),
           "bubbles": props(bubbleSize=0 if size else -8),
           "plotArea": [{"properties": {"image": {"image": {"name": lit("basemap.png"), "url": {"expr": {"ResourcePackageItem": {
               "PackageName": "RegisteredResources", "PackageType": 1, "ItemName": "basemap.png"}}}, "scaling": lit("Fit")}},
               "transparency": lit(0)}}]}
    return p.add("scatterChart", x, y, w, h, q, proj, obj, title=title)


def title_block(p, subtitle):
    p.text(20, 6, 860, 96, [[("SAANS · ", {"fontSize": "24pt", "fontWeight": "bold", "color": INK}),
                             ("Smog forecast for Pakistan", {"fontSize": "24pt", "fontWeight": "bold", "color": "#8fb8f0"})],
                            [(subtitle, {"fontSize": "10pt", "color": INK_2})]])


def forecast_panels(p, mode):
    """Everything below the slicers on the Live and Replay pages (the web dashboard's forecast view)."""
    top = 192
    # overview: all five cities for the chosen time, coloured by US EPA category (not filtered by the city slicer)
    q = Query()
    city = q.col("Cities", "City")
    refs = [q.measure("Forecasts", m) for m in ["Forecast next 24 h", "AQI next 24 h", "Risk level", "Chance AQI above 300", "Forecast 24-48 h", "Last 24 h"]]
    q.sort("Cities", "City")
    names = ["Forecast next 24 h (µg/m³)", "US EPA AQI", "Risk level (US EPA)", "Chance AQI > 300", "Next 24-48 h (µg/m³)", "Last 24 h (µg/m³)"]
    cf = [{"properties": {"backColor": measure_color("Forecasts", "Category colour"), "fontColor": measure_color("Forecasts", "Category text colour")},
           "selector": {"data": [{"dataViewWildcard": {"matchingOption": 1}}], "metadata": r}} for r in refs[:3]]
    overview = p.add("tableEx", 20, top, 1240, 238, q, {"Values": [city] + refs},
                     {"values": cf + props(fontSize=12, fontColorPrimary=color(INK), backColorPrimary=color(SURFACE), fontColorSecondary=color(INK),
                                           backColorSecondary=color(SURFACE_2)),
                      "columnHeaders": props(fontSize=10, fontColor=color(INK_2), backColor=color(SURFACE), wordWrap=True),
                      "grid": props(gridVertical=False, rowPadding=4, outlineColor=color(BORDER)), "total": props(totals=False)},
                     title="All five cities" + (" (forecast issued 08:00)" if mode == "Replay" else ""),
                     col_props={city: "City", **dict(zip(refs, names))})
    # map: cities as bubbles sized by forecast, coloured by risk level; fire detections of the previous 72 h
    mp = geo_map(p, 20, top + 245, 620, 470, "MapPoints", "point_id", "latitude", "longitude", "legend",
                 {**EPA, "Fire detections, last 72 h": FIRE}, "Forecast risk and upwind fires (bubble size = forecast, colour = US EPA category)",
                 size="size", tooltip="label")
    # 48-hour chart
    q = Query()
    t = q.col("Chart", "time_pkt")
    series = ["Observed (hourly)", "What actually happened", "Forecast (next 48 h)", "80% range low", "80% range high", "Hazardous (AQI 300)"]
    if mode == "Live":
        series.remove("What actually happened")
    ys = [q.measure("Chart", s) for s in series]
    q.sort("Chart", "time_pkt")
    cols = {"Observed (hourly)": INK, "What actually happened": INK_2, "Forecast (next 48 h)": ACCENT, "80% range low": "#5a8fd6", "80% range high": "#5a8fd6",
            "Hazardous (AQI 300)": "#d03b3b"}
    styles = {"What actually happened": "dashed", "80% range low": "dotted", "80% range high": "dotted", "Hazardous (AQI 300)": "dashed"}
    width = {"Forecast (next 48 h)": 4}
    obj = {"dataPoint": [{"properties": {"fill": color(cols[s])}, "selector": {"metadata": r}} for s, r in zip(series, ys)],
           "lineStyles": props(strokeWidth=2, showMarker=False) + [{"properties": {**({"lineStyle": lit(styles[s])} if s in styles else {}), **({"strokeWidth": lit(width[s])} if s in width else {})},
                                                                     "selector": {"metadata": r}} for s, r in zip(series, ys) if s in styles or s in width],
           "legend": props(show=True, position="Bottom", labelColor=color(INK_2), fontSize=9),
           "categoryAxis": props(labelColor=color(INK_2), showAxisTitle=False, gridlineShow=False),
           "valueAxis": props(labelColor=color(INK_2), showAxisTitle=True, titleText="PM2.5 (µg/m³)", titleColor=color(INK_2), gridlineColor=color(BORDER))}
    p.add("lineChart", 660, top + 245, 600, 470, q, {"Category": [t], "Y": ys}, obj, title="Selected city: recent hours and the 48-hour forecast")
    # why this forecast
    y2 = top + 730
    q = Query()
    g = q.col("Drivers", "driver_group")
    v = q.measure("Drivers", "Driver contribution")
    q.sort("Drivers", "group_order", kind="Column")
    dp = [{"properties": {"fill": color(c)}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0,
           "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "Drivers"}}, "Property": "driver_group"}}, "Right": {"Literal": {"Value": f"'{k}'"}}}}}]}}
          for k, c in DRIVERS.items()]
    p.add("clusteredBarChart", 20, y2, 620, 250, q, {"Category": [g], "Y": [v]},
          {"dataPoint": dp, "labels": props(show=True, color=color(INK), fontSize=10), "categoryAxis": props(labelColor=color(INK), fontSize=11),
           "valueAxis": props(show=True, labelColor=color(INK_2), showAxisTitle=True, titleText="µg/m³ above or below the typical level",
                              titleColor=color(INK_2), gridlineColor=color(BORDER))},
          title="Why this forecast? (SHAP driver groups)")
    p.text_card(20, y2 + 260, 620, 135, "Forecasts", "Why caption", size=10, ink=INK_2)
    # what-if
    p.slicer(660, y2, 600, 95, "Fire reduction", "Fire reduction", mode="Single", single=True, title="What if there were fewer upwind crop fires? Reduce fires by (%)")
    p.text_card(660, y2 + 105, 600, 150, "WhatIf", "What-if text", size=12)
    p.text_card(660, y2 + 265, 600, 100, "Forecasts", "Forecast details", size=10, ink=INK_2)
    # advisory
    y3 = y2 + 410
    p.text_card(20, y3, 620, 245, "Forecasts", "Advisory English", size=12, title="Health advisory (English)")
    p.text_card(660, y3, 600, 245, "Forecasts", "Advisory Urdu", size=14, title="صحت سے متعلق ہدایات (Urdu)")
    p.card(20, y3 + 253, 1240, 45, "Forecasts", "Advisory source", size=9, value_color=color(MUTED))
    return overview, mp, y3 + 310


def build_report():
    pages = []
    # ---------------------------------------------------------------- 1. Live forecast
    p = Page("Live forecast", height=1740)
    title_block(p, "Next 24 and 48 hours of PM2.5 for Lahore, Faisalabad, Multan, Islamabad and Karachi, explained with SHAP and "
                   "turned into English and Urdu advice. Built from OpenAQ sensors, NASA FIRMS fires, ERA5/Open-Meteo weather and an LLM news calendar.")
    p.card(900, 14, 360, 70, "Issues", "Issued", size=12, value_color=color("#8be38b"))
    p.card(20, 100, 1240, 46, "Live status", "Live status text", size=10, value_color=color(INK_2))
    city = p.slicer(20, 152, 1240, 34, "Cities", "City", mode="Basic", default="Lahore", horizontal=True, name="citySlicerLive")
    p.filters.append(in_filter("Issues", "mode", ["Live"], name="modeLive"))
    overview, mp, bottom = forecast_panels(p, "Live")
    p.no_filter += [(city, overview), (city, mp)]
    p.text(20, bottom, 1240, 60, [[("Known limits of the live mode: weather comes from the Open-Meteo forecast model rather than ERA5, the news event "
                                    "calendar is not updated live (event features are zero), and fire data are only included when NASA FIRMS answered "
                                    "the run. The forecasts are from the same models evaluated on the test seasons (see Model performance).",
                                    {"fontSize": "9pt", "color": MUTED})]])
    pages.append(p)
    # ---------------------------------------------------------------- 2. Replay
    p = Page("Replay: test seasons", height=1740)
    title_block(p, "Replays the forecasts issued at 08:00 every day of the two held-out smog seasons, which the models never saw, so each "
                   "forecast can be compared with what actually happened.")
    p.card(900, 14, 360, 70, "Issues", "Issued", size=12, value_color=color(INK_2))
    p.slicer(20, 104, 300, 62, "Issues", "season", mode="Dropdown", default="2024-25", title="Smog season")
    p.slicer(330, 104, 300, 62, "Issues", "date", mode="Dropdown", default="datetime'2024-11-06T00:00:00'", title="Forecast date (issued 08:00)", name="dateSlicer")
    city = p.slicer(640, 104, 620, 62, "Cities", "City", mode="Basic", default="Lahore", horizontal=True, title="City", name="citySlicerReplay")
    p.filters.append(in_filter("Issues", "mode", ["Replay"], name="modeReplay"))
    overview, mp, bottom = forecast_panels(p, "Replay")
    p.no_filter += [(city, overview), (city, mp)]
    p.card(20, bottom, 1240, 60, "Forecasts", "Replay check", size=12, value_color=color("#8be38b"))
    pages.append(p)
    # ---------------------------------------------------------------- 3. Model performance
    p = Page("Model performance", height=1200)
    title_block(p, "Trained on 1 Jan 2020 to 28 Sep 2024 and tested on two held-out smog seasons (October to January). "
                   "Skill = 1 - MAE(model) / MAE(persistence): above 0 means better than assuming tomorrow equals today.")
    q = Query()
    c, s = q.col("Model accuracy", "city"), q.col("Model accuracy", "season")
    v = q.measure("Model accuracy", "Skill vs persistence")
    hz = [in_filter("Model accuracy", "horizon", ["24 h"], name="h24")]
    hz[0].pop("isHiddenInViewMode")
    p.add("clusteredColumnChart", 20, 110, 620, 330, q, {"Category": [c], "Series": [s], "Y": [v]},
          {"dataPoint": [{"properties": {"fill": color(col)}, "selector": {"data": [{"scopeId": {"Comparison": {"ComparisonKind": 0,
            "Left": {"Column": {"Expression": {"SourceRef": {"Entity": "Model accuracy"}}, "Property": "season"}}, "Right": {"Literal": {"Value": f"'{k}'"}}}}}]}}
            for k, col in [("2024-25", ACCENT), ("2025-26", "#eb6834")]],
           "labels": props(show=True, color=color(INK), fontSize=9), "legend": props(show=True, position="Top", labelColor=color(INK_2)),
           "categoryAxis": props(labelColor=color(INK)), "valueAxis": props(labelColor=color(INK_2), gridlineColor=color(BORDER))},
          title="Next-24-hour forecast: skill vs persistence by city (Faisalabad and Multan were never in training)", filters=hz)
    q = Query()
    g, sh, pc = q.col("SHAP shares", "driver_group"), q.col("SHAP shares", "share_of"), q.agg("SHAP shares", "percent", 0)
    p.add("clusteredBarChart", 660, 110, 600, 330, q, {"Category": [g], "Series": [sh], "Y": [pc]},
          {"labels": props(show=True, color=color(INK), fontSize=9), "legend": props(show=True, position="Top", labelColor=color(INK_2)),
           "categoryAxis": props(labelColor=color(INK)), "valueAxis": props(labelColor=color(INK_2), gridlineColor=color(BORDER))},
          title="What drives the forecasts: SHAP share by driver group, 2024-25 test season (%)")
    for (entity, cols, names, y, h, ttl) in [
        ("Model accuracy", ["season", "horizon", "city", "hours", "mean_pm25", "MAE_model", "MAE_persistence", "MAE_seasonal", "skill_vs_persistence"],
         ["Season", "Horizon", "City", "Hours", "Mean PM2.5", "MAE SAANS", "MAE persistence", "MAE seasonal avg", "Skill"], 455, 300,
         "Forecast error (MAE, µg/m³) against both baselines"),
        ("Hazard warnings", ["season", "method", "hazardous_hours", "hit_rate", "false_alarm_ratio", "false_alarm_rate", "F1"],
         ["Season", "Method", "Hazardous hours", "Hit rate", "False alarm ratio", "False alarm rate", "F1"], 770, 170,
         "Hazard warnings: will the next 24 hours exceed AQI 300? (threshold 0.30, chosen on the 2023-24 validation season)"),
        ("Fire ablation", ["season", "subset", "hours", "MAE_with_fires", "MAE_without_fires", "MAE_change_from_fires"],
         ["Season", "Hours", "Test hours", "MAE with fire features", "MAE without", "Change from fires"], 955, 170,
         "Do the fire features help? The same model trained without them (negative change = fires reduce the error)")]:
        q = Query()
        refs = [q.col(entity, c) for c in cols]
        p.add("tableEx", 20, y, 1240, h, q, {"Values": refs},
              {"values": props(fontSize=10, fontColorPrimary=color(INK), backColorPrimary=color(SURFACE), fontColorSecondary=color(INK),
                               backColorSecondary=color(SURFACE_2)),
               "columnHeaders": props(fontSize=10, fontColor=color(INK_2), backColor=color(SURFACE), wordWrap=True),
               "total": props(totals=False)}, title=ttl, col_props=dict(zip(refs, names)))
    pages.append(p)
    # ---------------------------------------------------------------- 4. Data quality
    p = Page("Data quality", height=1250)
    title_block(p, "2,048,724 raw records cleaned through nine logged steps. Every number here is generated by notebook 02 "
                   "(reports/data_quality_report.md), not typed.")
    q = Query()
    src = q.col("Data received", "source")
    r1, r2 = q.agg("Data received", "received", 0), q.agg("Data received", "after_cleaning", 0)
    p.add("clusteredBarChart", 20, 110, 620, 300, q, {"Category": [src], "Y": [r1, r2]},
          {"dataPoint": [{"properties": {"fill": color(ACCENT)}, "selector": {"metadata": r1}}, {"properties": {"fill": color("#1baf7a")}, "selector": {"metadata": r2}}],
           "labels": props(show=True, color=color(INK), fontSize=9), "legend": props(show=True, position="Top", labelColor=color(INK_2)),
           "categoryAxis": props(labelColor=color(INK)), "valueAxis": props(labelColor=color(INK_2), gridlineColor=color(BORDER))},
          title="Records received and kept after cleaning, by source", col_props={r1: "Received", r2: "Kept"})
    geo_map(p, 660, 110, 600, 300, "Sensor map", "location", "lat", "lon", "type",
            {"Reference monitor": "#eda100", "Low-cost sensor": ACCENT},
            "PM2.5 sensors within 25 km of each city (uneven coverage is itself a finding)", tooltip="provider")
    for (entity, cols, names, y, h, ttl) in [
        ("Cleaning steps", ["step", "source", "action", "rows_before", "rows_after", "removed", "note"],
         ["Step", "Source", "Action", "Before", "After", "Removed", "Note"], 425, 520, "Every cleaning action, in order"),
        ("Sensors", ["provider", "sensors_received", "sensors_kept", "sensors_rejected", "hours_received", "hours_kept"],
         ["Provider", "Sensors received", "Kept", "Rejected", "Sensor-hours received", "Sensor-hours kept"], 960, 270,
         "Sensors received, kept and rejected (a sensor is kept if at least 24 valid hours survive)")]:
        q = Query()
        refs = [q.col(entity, c) for c in cols]
        if entity == "Cleaning steps":
            q.sort(entity, "order")
        p.add("tableEx", 20, y, 1240, h, q, {"Values": refs},
              {"values": props(fontSize=10, fontColorPrimary=color(INK), backColorPrimary=color(SURFACE), fontColorSecondary=color(INK),
                               backColorSecondary=color(SURFACE_2), wordWrap=True),
               "columnHeaders": props(fontSize=10, fontColor=color(INK_2), backColor=color(SURFACE), wordWrap=True), "total": props(totals=False)},
              title=ttl, col_props=dict(zip(refs, names)))
    pages.append(p)
    # ---------------------------------------------------------------- 5. Cleaned data
    p = Page("Cleaned data", height=1000)
    title_block(p, "The hourly master table produced by the cleaning: 266,760 city-hours, 2020 to January 2026 (one CSV per city in "
                   "data/processed/csv). Choose a city and a period.")
    p.slicer(20, 104, 400, 62, "Cleaned hourly", "city", mode="Dropdown", default="Lahore", title="City")
    q = Query()
    ref = q.col("Cleaned hourly", "date")
    obj = {"data": props(mode="Between"), "header": props(show=True, text="Period", fontColor=color(INK_2)),
           "general": [{"properties": {"filter": {"filter": {"Version": 2, "From": [{"Name": "f", "Entity": "Cleaned hourly", "Type": 0}],
                     "Where": [{"Condition": {"And": {
                         "Left": {"Comparison": {"ComparisonKind": 2, "Left": {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": "date"}},
                                                 "Right": {"Literal": {"Value": "datetime'2024-11-01T00:00:00'"}}}},
                         "Right": {"Comparison": {"ComparisonKind": 3, "Left": {"Column": {"Expression": {"SourceRef": {"Source": "f"}}, "Property": "date"}},
                                                  "Right": {"Literal": {"Value": "datetime'2024-11-08T00:00:00'"}}}}}}}]}}}}]}
    p.add("slicer", 430, 104, 830, 62, q, {"Values": [ref]}, obj)
    q = Query()
    t, v = q.col("Cleaned hourly", "time_pkt"), q.measure("Cleaned hourly", "Average PM2.5")
    p.add("lineChart", 20, 180, 1240, 300, q, {"Category": [t], "Y": [v]},
          {"dataPoint": [{"properties": {"fill": color(ACCENT)}, "selector": {"metadata": v}}], "categoryAxis": props(labelColor=color(INK_2)),
           "valueAxis": props(labelColor=color(INK_2), gridlineColor=color(BORDER))}, title="Cleaned hourly PM2.5 (µg/m³) for the chosen city and period")
    q = Query()
    cols = ["time_pkt", "pm25", "pm25_source", "pm25_interpolated", "long_gap", "pm10", "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
            "boundary_layer_height", "blh_imputed", "fires_300km", "extreme_event", "fireworks_night"]
    refs = [q.col("Cleaned hourly", c) for c in cols]
    q.sort("Cleaned hourly", "time_pkt")
    p.add("tableEx", 20, 495, 1240, 490, q, {"Values": refs},
          {"values": props(fontSize=9, fontColorPrimary=color(INK), backColorPrimary=color(SURFACE), fontColorSecondary=color(INK), backColorSecondary=color(SURFACE_2)),
           "columnHeaders": props(fontSize=9, fontColor=color(INK_2), backColor=color(SURFACE), wordWrap=True), "total": props(totals=False)},
          title="Hourly rows (every column is described in data/README.md)",
          col_props=dict(zip(refs, ["Time (PKT)", "PM2.5", "PM2.5 source", "Interpolated", "In long gap", "PM10", "Temp °C", "Humidity %",
                                    "Wind m/s", "Mixing height m", "BLH imputed", "Fires within 300 km", "Extreme event", "Fireworks night"])))
    pages.append(p)
    # ---------------------------------------------------------------- 6. How it works
    p = Page("How it works", height=900)
    title_block(p, "Smog Attribution And Nowcasting System. Data Science course project, SZABIST University Karachi. "
                   "Farhan Bashir (2312407), submitted to Sir Ahsan Nisar.")
    h = {"fontSize": "13pt", "fontWeight": "bold", "color": "#8fb8f0"}
    b = {"fontSize": "10.5pt", "color": INK}
    blocks = [
        ("Data", "OpenAQ PM2.5 and PM10 sensors (reference monitors and low-cost networks), NASA FIRMS satellite fire detections (VIIRS and MODIS), "
                 "ERA5 weather from Open-Meteo, and 2,255 Pakistani news headlines from GDELT; 1 January 2020 to 31 January 2026. "
                 "How each source was fetched and cleaned: docs/DATA_PIPELINE.md."),
        ("Cleaning", "Nine logged steps (timestamps, units, invalid and missing values, stuck sensors, spikes and dropouts, humidity correction "
                     "only where a pre-test check shows it helps, fire de-duplication, gaps, one hourly master table). See the Data quality page."),
        ("Features and models", "Upwind Fire Exposure Index (fires weighted by wind direction and distance), Stagnation Index, lags and calendar "
                                "flags. LightGBM predicts the change of the next 24-hour mean (and the 24 hours after), with an 80% band and a "
                                "classifier for AQI above 300. Time-based split: trained to Sep 2024, tested on 2024-25 and 2025-26."),
        ("Explanations and advice", "SHAP splits every forecast into four driver groups (recent pollution, weather, upwind fires, calendar). "
                                    "A Large Language Model (Gemini, Groq as fallback) extracted the event calendar from news and writes the "
                                    "English and Urdu advisories; every number it writes must come from the model, or a template is used."),
        ("This Power BI report", "Loads the project's exported tables (powerbi/data) from GitHub; Refresh picks up the newest live snapshot, "
                                 "written daily by the repository's scheduled job. It shows precomputed forecasts and runs no model itself, "
                                 "like the web dashboard's snapshot mode."),
        ("Limits", "Attribution is statistical, not chemical. Lahore's 2025-26 forecasts run high (about 21 µg/m³) after the reference monitor "
                   "stopped and only low-cost networks remained. The event calendar is noisy (76% strict accuracy on a random 50)."),
    ]
    y = 110
    for head, body in blocks:
        p.text(20, y, 1240, 105, [[(head, h)], [(body, b)]], background=True)
        y += 115
    p.text(20, y, 1240, 60, [[("Code and data: ", b), ("github.com/FarhanRajputFelix/saans", {**b, "color": ACCENT}, "https://github.com/FarhanRajputFelix/saans"),
                              ("   ·   Web dashboard: ", b),
                              ("saansgit-uhebsjzld3rfqxupnygsop.streamlit.app", {**b, "color": ACCENT}, "https://saansgit-uhebsjzld3rfqxupnygsop.streamlit.app/")]],
           background=True)
    pages.append(p)
    return pages


def theme():
    return {
        "name": "SAANS dark",
        "dataColors": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"],
        "background": BG, "foreground": INK, "tableAccent": ACCENT,
        "textClasses": {"callout": {"fontSize": 22, "fontFace": "Segoe UI Semibold", "color": INK},
                        "title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": INK},
                        "header": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": INK},
                        "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": INK_2}},
        "visualStyles": {
            "*": {"*": {"background": [{"show": True, "color": {"solid": {"color": SURFACE}}, "transparency": 0}],
                        "border": [{"show": True, "color": {"solid": {"color": BORDER}}, "radius": 10}],
                        "title": [{"fontColor": {"solid": {"color": INK}}}],
                        "visualHeader": [{"background": {"solid": {"color": SURFACE}}, "foreground": {"solid": {"color": INK_2}}}]}},
            "page": {"*": {"background": [{"color": {"solid": {"color": BG}}, "transparency": 0}],
                           "outspace": [{"color": {"solid": {"color": BG}}, "transparency": 0}]}},
            "filter": {"*": {"background": [{"color": {"solid": {"color": SURFACE}}}]}},
        },
    }


def write():
    root = HERE
    for d in [root / f"{NAME}.Report", root / f"{NAME}.SemanticModel"]:
        if d.exists():
            shutil.rmtree(d)
    sm, rp = root / f"{NAME}.SemanticModel", root / f"{NAME}.Report"
    (rp / "StaticResources" / "RegisteredResources").mkdir(parents=True)
    sm.mkdir(parents=True)
    dump = lambda path, obj: path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    dump(root / f"{NAME}.pbip", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                                 "version": "1.0", "artifacts": [{"report": {"path": f"{NAME}.Report"}}], "settings": {"enableAutoRecovery": True}})
    dump(sm / "definition.pbism", {"version": "1.0", "settings": {}})
    dump(sm / "model.bim", semantic_model())
    dump(rp / "definition.pbir", {"version": "1.0", "datasetReference": {"byPath": {"path": f"../{NAME}.SemanticModel"}, "byConnection": None}})
    dump(rp / "StaticResources" / "RegisteredResources" / "SAANS_dark.json", theme())
    shutil.copy(HERE / "basemap.png", rp / "StaticResources" / "RegisteredResources" / "basemap.png")
    pages = build_report()
    report = {
        "config": json.dumps({"version": "5.43", "themeCollection": {"customTheme": {"name": "SAANS_dark.json", "version": "5.43", "type": 1}},
                              "activeSectionIndex": 0, "defaultDrillFilterOtherVisuals": True,
                              "settings": {"useNewFilterPaneExperience": True, "allowChangeFilterTypes": True, "useStylableVisualContainerHeader": True,
                                           "exportDataMode": 1}}),
        "layoutOptimization": 0,
        "resourcePackages": [{"resourcePackage": {"name": "RegisteredResources", "type": 1, "disabled": False,
                                                  "items": [{"name": "SAANS_dark.json", "path": "SAANS_dark.json", "type": 202},
                                                            {"name": "basemap.png", "path": "basemap.png", "type": 100}]}}],
        "sections": [pg.section(i) for i, pg in enumerate(pages)],
    }
    dump(rp / "report.json", report)
    print(f"wrote {NAME}.pbip: {len(pages)} pages, {sum(len(pg.visuals) for pg in pages)} visuals, "
          f"{len(semantic_model()['model']['tables'])} tables")


if __name__ == "__main__":
    write()
