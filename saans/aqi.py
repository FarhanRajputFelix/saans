"""US EPA Air Quality Index for PM2.5, using the breakpoints EPA revised in February 2024.

AQI is defined on the 24-hour mean concentration. We compute it ourselves from ug/m3 instead of
copying published AQI figures, because Pakistani and international sites mix different scales
(the "AQI 1,165" reported for Lahore in Nov 2024 is beyond the official 0-500 range).
"""
import numpy as np

# (concentration low, concentration high, AQI low, AQI high, category)
BREAKPOINTS = [
    (0.0, 9.0, 0, 50, "Good"),
    (9.1, 35.4, 51, 100, "Moderate"),
    (35.5, 55.4, 101, 150, "Unhealthy for Sensitive Groups"),
    (55.5, 125.4, 151, 200, "Unhealthy"),
    (125.5, 225.4, 201, 300, "Very Unhealthy"),
    (225.5, 325.4, 301, 500, "Hazardous"),
]
HAZARDOUS_PM25 = 225.5  # a 24-hour mean at or above this is AQI > 300, the project's "hazardous day"

# EPA's official colour for each category. Everything that shows a risk level (tiles, map, advisory)
# uses these six categories, so a forecast can never be "Yellow" on a tile and "Unhealthy" in its advice.
CATEGORY_COLORS = {"Good": "#00e400", "Moderate": "#ffff00", "Unhealthy for Sensitive Groups": "#ff7e00",
                   "Unhealthy": "#ff0000", "Very Unhealthy": "#8f3f97", "Hazardous": "#7e0023"}
SHORT_NAMES = {"Unhealthy for Sensitive Groups": "Unhealthy (sensitive)"}


def pm25_to_aqi(conc):
    """AQI for one value or an array of 24-hour mean PM2.5 (ug/m3). Above 325.4 the top
    segment is extended linearly, so extreme days read above 500 instead of being capped."""
    c = np.floor(np.asarray(conc, dtype=float) * 10) / 10  # EPA truncates to one decimal
    aqi = np.full(c.shape, np.nan)
    for lo, hi, a_lo, a_hi, _ in BREAKPOINTS:
        top = np.inf if hi == BREAKPOINTS[-1][1] else hi + 0.05
        m = (c >= lo) & (c < top)
        aqi[m] = (a_hi - a_lo) / (hi - lo) * (c[m] - lo) + a_lo
    return np.round(aqi)


def category(pm25_24h: float) -> str:
    """EPA category name for a 24-hour mean PM2.5, truncated like pm25_to_aqi so the name always matches
    the AQI number (55.46 is AQI 150, "Unhealthy for Sensitive Groups", not "Unhealthy")."""
    c = np.floor(pm25_24h * 10) / 10
    return next((name for lo, hi, a, b, name in BREAKPOINTS if c <= hi), "Hazardous")


def risk_level(pm25_24h: float) -> tuple[str, str]:
    """(EPA category, official colour) for a 24-hour mean PM2.5 forecast."""
    c = category(pm25_24h)
    return c, CATEGORY_COLORS[c]
