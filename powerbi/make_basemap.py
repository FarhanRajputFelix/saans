"""Draw the dark basemap behind the Power BI map (powerbi/basemap.png).

Power BI's own map visuals need either a setting the user must switch on (Map) or a signed-in account (Azure Maps),
so the report plots cities and fires on a scatter chart whose axes are pinned to this image's extent: a map that
works on any computer, offline. Country borders: Natural Earth 1:50m (public domain), downloaded once.

Run from the repository root:  python powerbi/make_basemap.py
"""
import json
import tempfile
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Polygon  # noqa: E402

HERE = Path(__file__).parent
SOURCE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson"
# map extent (degrees). The longitude span is chosen so that, in a plot area about 1.5 times wider than tall,
# one degree of longitude is drawn cos(30 N) times one degree of latitude: no visible stretching over Pakistan.
LON0, LON1, LAT0, LAT1 = 60.5, 82.5, 23.0, 36.5
WIDTH_PX = 1500
SEA, LAND, LAND_PK, BORDER, LABEL = "#0b0e14", "#1b2029", "#232a36", "#4a5263", "#6b7385"
NAMES = {"Pakistan": (69.6, 29.6), "India": (78.3, 26.0), "Afghanistan": (64.6, 33.6), "Iran": (61.4, 27.4)}


def main():
    cache = Path(tempfile.gettempdir()) / "ne_50m_admin_0_countries.geojson"
    if not cache.exists():
        urllib.request.urlretrieve(SOURCE, cache)
    countries = json.loads(cache.read_text(encoding="utf-8"))["features"]

    aspect = (LON1 - LON0) * 0.866 / (LAT1 - LAT0)
    fig = plt.figure(figsize=(WIDTH_PX / 100, WIDTH_PX / 100 / aspect), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(LON0, LON1)
    ax.set_ylim(LAT0, LAT1)
    ax.set_facecolor(SEA)
    ax.axis("off")
    for f in countries:
        geom = f["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        fill = LAND_PK if f["properties"].get("ADMIN") == "Pakistan" else LAND
        for poly in polys:
            ax.add_patch(Polygon(poly[0], closed=True, facecolor=fill, edgecolor=BORDER, linewidth=1.1))
    for name, (x, y) in NAMES.items():
        ax.text(x, y, name, color=LABEL, fontsize=15, ha="center", va="center", fontweight="bold")
    out = HERE / "basemap.png"
    fig.savefig(out, dpi=100, facecolor=SEA)
    print(out, f"extent lon {LON0}-{LON1}, lat {LAT0}-{LAT1}")


if __name__ == "__main__":
    main()
