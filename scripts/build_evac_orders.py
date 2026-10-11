"""Build data/processed/eaton/evac_orders.jsonl from the real emergency alerts of the night.

Source: LA County's layer of the IPAWS alerts (Wireless Emergency Alerts to phones) sent
during the January 2025 fires: when each alert went out, its words, and the exact area it
went to. One row per alert that reached the study area between 6 p.m. Jan 7 and 6 a.m. Jan 8.
An alert's area is the union of the evacuation zones it was sent for.

- Kind from the alert's own words: "EVACUATION ORDER" = order, "EVACUATION WARNING" =
  warning, "BE AWARE" = advisory (Citygate calls the 6:48 p.m. alerts advisory
  notifications, not warnings).
- The layer stores send times as Pacific clock time labelled UTC. Read that way they match
  Citygate's tables to the minute (6:48/6:49 p.m., 7:26, 7:55, 9:00, 10:43 p.m.; 3:25,
  3:36, 4:36 a.m.), so that is how they are read.
- Zone names (ALD-EASTLOMA, ...) come from Citygate's tables where the time matches.

These replace street boxes we had drawn ourselves, which put the 3:25 a.m. order over
south-west Altadena: those streets were ordered between 5:15 and 5:56 a.m.

    uv run python scripts/build_evac_orders.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import h3

from backend.knowledge import _inside
from backend.schemas import EvacOrder
from backend.store import DATA_DIR, DATASETS, grid_cells, write_jsonl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eaton_timeline import CITYGATE_PDF  # noqa: E402

IPAWS_LAYER = (
    "https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services/"
    "IPAWS_Jan_2025_Fire_Alerts/FeatureServer/2"
)
RAW = DATA_DIR / "raw" / "ipaws" / "jan2025_fire_alerts.json"
PT = timezone(timedelta(hours=-8))
START = datetime(2025, 1, 7, 18, 0, tzinfo=PT)
END = datetime(2025, 1, 8, 6, 0, tzinfo=PT)

# Send time (Pacific) -> (zones, Citygate table). Alerts not listed here (after 5 a.m.,
# Citygate's last table) keep the alert's own words as their area.
CITYGATE = {
    "01-07 18:49": ("Advisory, 12 zones on three sides of the origin: ALD-EASTLOMA, "
                    "ALD-EATONCANYON, ALD-GARFIAS, ALD-MENDOCINO, ALD-MIDLOTHIAN, KIN-KINNELOA, "
                    "PAS-E014 to PAS-E019", "Table 1 / Finding #4 (6:48 p.m.)"),
    "01-07 19:26": ("Order, 5 Altadena zones east of Lake Avenue, Kinneloa Mesa and 1 Pasadena "
                    "zone: ALD-EASTLOMA, ALD-EATONCANYON, ALD-GARFIAS, ALD-MENDOCINO, "
                    "ALD-MIDLOTHIAN, KIN-KINNELOA, PAS-019", "Table 2 / Finding #5"),
    "01-07 19:55": ("Warning: ALD-MOUNTLOWE, PAS-E014 to PAS-E018", "Table 2"),
    "01-07 21:00": ("Order, 2 Altadena zones immediately east of Lake Avenue",
                    "Table 3 / Finding #8"),
    "01-07 22:43": ("Warning, 2 Pasadena zones", "Table 4"),
    "01-08 03:25": ("Order, 13 zones west of Lake Avenue: ALD-ARROYOSECO, ALD-CANON, "
                    "ALD-CASITAS, ALD-CHANEY, ALD-FARNSWORTH, ALD-GARDEN, ALD-LAUREL, "
                    "ALD-MEADOWS, ALD-MILLARD, ALD-PALM, ALD-WAPELLO, ALD-WHITEPARK, LCF-JPL",
                    "Table 7 / Finding #20"),
    "01-08 03:36": ("Warning, 6 La Cañada Flintridge zones", "§2.5 / Table 7"),
    "01-08 04:36": ("Order, the same 6 La Cañada Flintridge zones", "§2.5 / Table 7"),
}


def download() -> None:
    query = urllib.parse.urlencode({
        "where": "1=1", "outFields": "Identifier,Sent,Event,CMAMtext,SenderName",
        "returnGeometry": "true", "outSR": "4326", "f": "json",
    })
    with urllib.request.urlopen(f"{IPAWS_LAYER}/query?{query}", timeout=60) as r:
        data = json.load(r)
    RAW.parent.mkdir(parents=True, exist_ok=True)
    RAW.write_text(json.dumps(data))


def sent_at(ms: int) -> datetime:
    """The layer's 'UTC' send time is really Pacific clock time (see the docstring)."""
    return datetime.fromtimestamp(ms / 1000, UTC).replace(tzinfo=PT)


def kind_of(text: str) -> str:
    words = text.upper()
    if "EVACUATION ORDER" in words:
        return "order"
    if "EVACUATION WARNING" in words:
        return "warning"
    if "BE AWARE" in words:
        return "advisory"
    raise ValueError(f"can't tell the alert kind from: {text!r}")


def build(data: dict | None = None) -> list[EvacOrder]:
    data = data or json.loads(RAW.read_text())
    meta = json.loads((DATASETS["eaton"] / "meta.json").read_text())
    centres = [h3.cell_to_latlng(c) for c in grid_cells(meta["bbox"])]
    out = []
    for f in data["features"]:
        a = f["attributes"]
        t = sent_at(a["Sent"])
        if not START <= t <= END:
            continue
        (ring,) = f["geometry"]["rings"]
        ring = [[round(x, 5), round(y, 5)] for x, y in ring]
        if ring[0] != ring[-1]:
            raise ValueError(f"{a['Identifier']}: alert area is not a closed ring")
        if not any(_inside(lon, lat, ring) for lat, lon in centres):
            continue  # another fire, or outside the study area
        text = " ".join(a["CMAMtext"].split())
        zones, table = CITYGATE.get(f"{t:%m-%d %H:%M}", (None, None))
        source = f"LA County, IPAWS Jan 2025 Fire Alerts, {a['Identifier']}, {IPAWS_LAYER}"
        if table:
            source += f"; zones: {CITYGATE_PDF}, {table}"
        out.append(EvacOrder(
            zone_id=f"wea-{t:%m%d-%H%M}", kind=kind_of(text), issued_at=t,
            area=zones or text, polygon=ring, source=source,
        ))
    return sorted(out, key=lambda o: o.issued_at)


def main() -> None:
    download()
    orders = build()
    path = DATASETS["eaton"] / "evac_orders.jsonl"
    write_jsonl(path, orders)
    print(f"Wrote {len(orders)} alerts that reached the study area -> {path}")
    for o in orders:
        print(f"  {o.issued_at:%b %d %H:%M}  {o.kind:8s}  {o.area[:60]}")


if __name__ == "__main__":
    main()
