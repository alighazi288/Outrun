"""Build data/processed/eaton/evac_orders.jsonl from Genasys zone times.

Times and zone ids are Citygate's tables (cross-checked with McChrystal and NBC).
Polygons are reconstructed street boxes, not official Genasys shapefiles: Lake
Avenue is the east/west split the investigations use. One row per zone; a zone
that is first warned and later ordered appears twice (kind=warning, then order).

Zones outside the Altadena study (Sierra Madre, Arcadia, Monrovia, Hurst) are
omitted: they do not cover the replay population. NBC's 5:42 a.m. order for two
deaths is not in Citygate's zone list through 5:01 a.m., so it is not invented.

    uv run python scripts/build_evac_orders.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.clock import parse_t
from backend.schemas import EvacOrder
from backend.store import DATASETS, write_jsonl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eaton_timeline import (  # noqa: E402
    CITYGATE_PDF,
    EAST_ALTADENA,
    JPL,
    KINNELOA,
    MCCHRYSTAL_PDF,
    MOUNT_LOWE,
    NBC,
    PASADENA_NORTH,
    WEST_ALTADENA,
)

Kind = str  # "warning" | "order"

# (zone_id, kind, issued_at, area, polygon, citation)
ROWS: list[tuple[str, Kind, str, str, list[list[float]], str]] = []

_EAST_ZONES = (
    "ALD-EASTLOMA", "ALD-EATONCANYON", "ALD-GARFIAS", "ALD-MENDOCINO", "ALD-MIDLOTHIAN",
)
_PAS_WARN_648 = tuple(f"PAS-E01{n}" for n in range(4, 10))  # E014–E019
_WEST_ZONES = (
    "ALD-ARROYOSECO", "ALD-CANON", "ALD-CASITAS", "ALD-CHANEY", "ALD-FARNSWORTH",
    "ALD-GARDEN", "ALD-LAUREL", "ALD-MEADOWS", "ALD-MILLARD", "ALD-PALM",
    "ALD-WAPELLO", "ALD-WHITEPARK",
)


def _add(zone: str, kind: Kind, when: str, area: str, polygon: list[list[float]],
         cite: str) -> None:
    ROWS.append((zone, kind, when, area, polygon, cite))


# 6:48 p.m. advisory / WEA "BE AWARE" to 12 zones on three sides of the origin.
_CITE_648 = (
    f"{CITYGATE_PDF}, Table 1 / Finding #4; {MCCHRYSTAL_PDF}; {NBC} (6:48 p.m. east of Lake)"
)
for z in _EAST_ZONES:
    _add(z, "warning", "2025-01-07T18:48:00-08:00",
         "Altadena east of Lake Avenue", EAST_ALTADENA, _CITE_648)
_add("KIN-KINNELOA", "warning", "2025-01-07T18:48:00-08:00",
     "Kinneloa Mesa", KINNELOA, _CITE_648)
for z in _PAS_WARN_648:
    _add(z, "warning", "2025-01-07T18:48:00-08:00",
         "Pasadena north of I-210, east of Lake Avenue", PASADENA_NORTH, _CITE_648)

# 7:26 p.m. first evacuation orders (LEAVE NOW).
_CITE_726 = f"{CITYGATE_PDF}, Table 2 / Finding #5; {MCCHRYSTAL_PDF}; {NBC}"
for z in _EAST_ZONES:
    _add(z, "order", "2025-01-07T19:26:00-08:00",
         "Altadena east of Lake Avenue", EAST_ALTADENA, _CITE_726)
_add("KIN-KINNELOA", "order", "2025-01-07T19:26:00-08:00",
     "Kinneloa Mesa", KINNELOA, _CITE_726)
_add("PAS-019", "order", "2025-01-07T19:26:00-08:00",
     "Pasadena zone PAS-019", PASADENA_NORTH, _CITE_726)

# 7:55 p.m. warnings immediately east of Lake, plus remaining Pasadena E-zones.
_CITE_755 = f"{CITYGATE_PDF}, Table 2"
_add("ALD-MOUNTLOWE", "warning", "2025-01-07T19:55:00-08:00",
     "Altadena immediately east of Lake Avenue (Mount Lowe)", MOUNT_LOWE, _CITE_755)
for z in ("PAS-E014", "PAS-E015", "PAS-E016", "PAS-E017", "PAS-E018"):
    _add(z, "warning", "2025-01-07T19:55:00-08:00",
         "Pasadena north of I-210, east of Lake Avenue", PASADENA_NORTH, _CITE_755)

# 9:00 p.m. order for two Altadena zones immediately east of Lake.
# ALD-MENDOCINO was already ordered at 7:26; only Mount Lowe is new.
_CITE_2100 = f"{CITYGATE_PDF}, Table 3 / Finding #8"
_add("ALD-MOUNTLOWE", "order", "2025-01-07T21:00:00-08:00",
     "Altadena immediately east of Lake Avenue (Mount Lowe)", MOUNT_LOWE, _CITE_2100)

# 3:25 a.m. orders west of Lake (12 Altadena zones + LCF-JPL).
_CITE_325 = (
    f"{CITYGATE_PDF}, Table 7 / Finding #20; {MCCHRYSTAL_PDF}; {NBC} (3:25 a.m. west of Lake)"
)
for z in _WEST_ZONES:
    _add(z, "order", "2025-01-08T03:25:00-08:00",
         "Altadena west of Lake Avenue", WEST_ALTADENA, _CITE_325)
_add("LCF-JPL", "order", "2025-01-08T03:25:00-08:00",
     "La Cañada Flintridge / JPL", JPL, _CITE_325)


def build() -> list[EvacOrder]:
    seen: set[tuple[str, str, str]] = set()
    out: list[EvacOrder] = []
    for zone_id, kind, when, area, polygon, source in ROWS:
        key = (zone_id, kind, when)
        if key in seen:
            raise ValueError(f"duplicate order row {key}")
        seen.add(key)
        if polygon[0] != polygon[-1]:
            raise ValueError(f"{zone_id}: polygon must be a closed ring")
        out.append(EvacOrder(
            zone_id=zone_id,
            kind=kind,  # type: ignore[arg-type]
            issued_at=parse_t(when),
            area=area,
            polygon=polygon,
            source=source,
        ))
    return out


def main() -> None:
    orders = build()
    path = DATASETS["eaton"] / "evac_orders.jsonl"
    write_jsonl(path, orders)
    print(f"Wrote {len(orders)} evacuation rows -> {path}")
    for kind in ("warning", "order"):
        n = sum(o.kind == kind for o in orders)
        print(f"  {n} {kind}s")
    west = [o for o in orders if o.kind == "order" and o.issued_at.hour == 3]
    print(f"  {len(west)} orders at 3:25 a.m. (west of Lake + JPL)")


if __name__ == "__main__":
    main()
