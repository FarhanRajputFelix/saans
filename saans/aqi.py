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

# The dashboard's four forecast risk levels (upper PM2.5 bound, label, status colour role)
RISK_LEVELS = [(35.4, "Green", "good"), (125.4, "Yellow", "warning"),
               (225.4, "Orange", "serious"), (np.inf, "Red", "critical")]


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


def risk_level(pm25_24h: float) -> tuple[str, str]:
    """(label, status colour role) for a 24-hour mean PM2.5 forecast."""
    for upper, label, role in RISK_LEVELS:
        if pm25_24h <= upper:
            return label, role
    return RISK_LEVELS[-1][1], RISK_LEVELS[-1][2]
