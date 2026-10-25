"""AI Smog Explainer: a three-line English and Urdu advisory from the model's numbers.

Guardrails (proposal, "LLM Integration"):
1. the LLM never predicts; it only rewords the numbers it is given;
2. every number in its answer must be one we supplied, or the answer is discarded;
3. a rule-based bilingual template is used whenever the LLM is unavailable or fails the check;
4. answers are cached (saans/llm.py), once per city per day.
"""
import json
import re

from saans import llm
from saans.aqi import category, pm25_to_aqi
from saans.config import CITIES

URDU_NAMES = {"lahore": "لاہور", "faisalabad": "فیصل آباد", "multan": "ملتان", "islamabad": "اسلام آباد", "karachi": "کراچی"}
URDU_GROUPS = {"Recent pollution": "حالیہ آلودگی", "Weather": "موسم اور ہوا کا جمود",
               "Upwind fires": "ہوا کے رخ پر فصلوں کی آگ", "Calendar": "موسم اور تہوار کا کیلنڈر"}
URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

PROMPT = """You are the "AI Smog Explainer" of SAANS, a smog forecasting system for Pakistan.
Write a health advisory for residents of {city} for the next 24 hours (forecast issued {date}, 08:00 Pakistan time).

Use ONLY these numbers, exactly as written. Do not calculate, round differently or invent any other number:
- forecast 24-hour mean PM2.5: {f} micrograms per cubic metre
- US EPA AQI: {aqi} ({category})
- chance that the next 24 hours are hazardous (AQI above 300): {p}%
- main reasons, from the model's explanation: {drivers}

Write exactly three short lines in plain English:
1. the forecast and the AQI;
2. why, naming the main reasons in everyday words;
3. what people should do, with care for children, the elderly and people with asthma.
Then write the same three lines in natural, simple Urdu (Urdu script).

Return JSON: {{"en": "<three lines separated by \\n>", "ur": "<three lines separated by \\n>"}}"""

ADVICE = {  # one line of advice per US EPA category
    "Good": ("Air quality is good; normal outdoor activity is fine.", "ہوا کا معیار اچھا ہے، معمول کی بیرونی سرگرمیاں جاری رکھیں۔"),
    "Moderate": ("Air is acceptable; unusually sensitive people should limit long outdoor exertion.",
                 "ہوا قابلِ قبول ہے؛ بہت حساس افراد طویل بیرونی مشقت کم کریں۔"),
    "Unhealthy for Sensitive Groups": ("Children, the elderly and people with asthma or heart disease should cut long or heavy outdoor activity.",
                                       "بچے، بزرگ اور دمہ یا دل کے مریض طویل یا سخت بیرونی سرگرمی کم کریں۔"),
    "Unhealthy": ("Everyone should limit time outdoors; sensitive groups should stay indoors and wear a mask outside.",
                  "سب لوگ باہر کم وقت گزاریں؛ حساس افراد گھر کے اندر رہیں اور باہر ماسک پہنیں۔"),
    "Very Unhealthy": ("Avoid outdoor activity, keep windows closed and wear an N95 mask if you must go out.",
                       "بیرونی سرگرمیوں سے گریز کریں، کھڑکیاں بند رکھیں اور باہر جانا ضروری ہو تو N95 ماسک پہنیں۔"),
    "Hazardous": ("Hazardous smog: stay indoors, keep windows shut and use an N95 mask if you must go out.",
                  "خطرناک سموگ: گھر کے اندر رہیں، کھڑکیاں بند رکھیں اور باہر جانا ضروری ہو تو N95 ماسک پہنیں۔"),
}


def facts(city: str, date: str, forecast: float, hazard_prob: float, top_drivers: str) -> dict:
    drivers = json.loads(top_drivers)
    return {"city": CITIES[city].name, "date": date, "f": int(round(forecast)), "aqi": int(pm25_to_aqi(forecast)),
            "category": category(forecast), "p": int(round(100 * hazard_prob)),
            "drivers": "; ".join(d["label"].lower() for d in drivers), "groups": [d["group"] for d in drivers]}


def numbers_ok(text: str, fx: dict) -> bool:
    """Every number in the text must be one we supplied (Urdu digits are normalised first)."""
    allowed = {str(fx["f"]), str(fx["aqi"]), str(fx["p"]), "2.5", "24", "300", "95", "8", "08", "00", "1", "2", "3"}
    allowed |= set(re.findall(r"\d+(?:\.\d+)?", fx["date"]))
    return all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", text.translate(URDU_DIGITS)))


def template(city: str, fx: dict) -> dict:
    level = fx["category"]
    groups = list(dict.fromkeys(fx["groups"]))[:2] or ["Recent pollution"]
    en_why = " and ".join(g.lower() for g in groups)
    ur_why = " اور ".join(URDU_GROUPS[g] for g in groups)
    return {"source": "template",
            "en": f"{fx['city']}: the next 24 hours are forecast to average {fx['f']} µg/m³ of PM2.5 (AQI {fx['aqi']}, {fx['category']}).\n"
                  f"Main drivers: {en_why}.\n{ADVICE[level][0]}",
            "ur": f"{URDU_NAMES[city]} میں آئندہ 24 گھنٹوں کے دوران PM2.5 کی اوسط سطح {fx['f']} مائیکروگرام فی مکعب میٹر (AQI {fx['aqi']}) متوقع ہے۔\n"
                  f"بڑی وجوہات: {ur_why}۔\n{ADVICE[level][1]}"}


def write(city: str, date: str, forecast: float, hazard_prob: float, top_drivers: str, use_llm: bool = True) -> dict:
    """LLM advisory if it passes the number check, otherwise the template."""
    fx = facts(city, date, forecast, hazard_prob, top_drivers)
    if use_llm:
        try:
            answer, provider = llm.ask(PROMPT.format(**fx), temperature=0.4, as_json=True)
            out = llm.parse_json(answer)
            if numbers_ok(out["en"], fx) and numbers_ok(out["ur"], fx):
                return {"en": out["en"], "ur": out["ur"], "source": provider}
        except Exception:
            pass
    return template(city, fx)
