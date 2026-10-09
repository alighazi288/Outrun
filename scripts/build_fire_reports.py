"""Build data/processed/eaton/fire_reports.jsonl from the published timelines.

Hand-extracted. Each row is one timestamped report of fire that a published
investigation names (Citygate tables, McChrystal AAR, FSRI timeline via LAT).
Satellite detections stay in detections.jsonl. Personal 911 recordings are not used.
A report that only says fire was *visible from* a street is not a fire location
(FSRI/LAT East Calaveras, 10:50 p.m.): putting it here would mark that hex burning.

Precision (data/BUILD.md): 250 m for a named intersection or hundred-block,
500 m for a named street with no block, 1000 m for a canyon, flank, or area.

    uv run python scripts/build_fire_reports.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import h3

from backend.clock import parse_t
from backend.schemas import H3_RES, FireReport
from backend.store import DATASETS, write_jsonl

sys.path.insert(0, str(Path(__file__).resolve().parent))
from eaton_timeline import (  # noqa: E402
    AREA_M,
    CITYGATE_PDF,
    FSRI_VIA_LAT,
    MCCHRYSTAL_PDF,
    PLACES,
    STREET_M,
    STREET_ONLY_M,
)

# (id, reported_at Pacific, place key, precision_m, description, citation)
# Descriptions stay close to the source wording. House numbers that the source
# publishes (McChrystal 500 E Las Flores; Citygate hundred-blocks) are kept;
# redacted private 911 addresses are not.
ROWS: list[tuple[str, str, str, float, str, str]] = [
    (
        "fr_origin", "2025-01-07T18:18:00-08:00", "eaton_canyon", AREA_M,
        "Eaton Fire reported in Eaton Canyon.",
        f"{MCCHRYSTAL_PDF}, timeline (matches meta.json fire_start); "
        f"{CITYGATE_PDF}, §1.2 (~6:15 p.m.)",
    ),
    (
        "fr_altadena_dr_spots", "2025-01-07T18:54:00-08:00", "altadena_dr_east", AREA_M,
        "Helicopter coordinator: fire skirting along Altadena Drive toward Kinneloa; "
        "spot fires short of Kinneloa Canyon.",
        f"{CITYGATE_PDF}, Table 2",
    ),
    (
        "fr_hospital", "2025-01-07T20:04:00-08:00", "hospital", STREET_M,
        "Flames reported threatening Pasadena Park Convalescent Hospital on East "
        "Washington Boulevard, about 1.5 miles east of Lake Avenue.",
        f"{CITYGATE_PDF}, Table 2",
    ),
    (
        "fr_kinneloa_hastings", "2025-01-07T20:40:00-08:00", "kinneloa", AREA_M,
        "Fire has spread into Kinneloa Mesa and Hastings Ranch with multiple houses on fire.",
        f"{CITYGATE_PDF}, Table 2 (8:40–9:09 p.m.)",
    ),
    (
        "fr_west_of_origin", "2025-01-07T21:30:00-08:00", "west_of_origin", AREA_M,
        "Fire spread to the west; several spot fires west of the origin.",
        f"{FSRI_VIA_LAT} (as early as 9:30 p.m.); {CITYGATE_PDF}, §2.1 n.13 cites FSRI p.173",
    ),
    (
        "fr_toward_lake", "2025-01-07T22:22:00-08:00", "toward_lake", AREA_M,
        "Radio calls: fire spreading west toward North Lake Avenue.",
        f"{FSRI_VIA_LAT} (from 10:22 p.m. through the next hour)",
    ),
    (
        "fr_midwick", "2025-01-07T22:50:00-08:00", "midwick_glen_canyon", STREET_M,
        "Multiple houses and vegetation on fire around Midwick Drive and Glen Canyon Road, "
        "about 3/4 mile east of Lake Avenue.",
        f"{CITYGATE_PDF}, Table 4",
    ),
    (
        "fr_mendocino", "2025-01-07T23:01:00-08:00", "mendocino_midlothian", STREET_M,
        "LACoSD: two structures on fire on East Mendocino Lane and North Midlothian Drive "
        "(east of Lake Avenue).",
        f"{CITYGATE_PDF}, Table 4",
    ),
    (
        "fr_west_flank", "2025-01-07T23:18:00-08:00", "toward_lake", AREA_M,
        "At least 10 fire reports on the western flank between 11:18 p.m. and 12:17 a.m., "
        "showing the advance toward Lake Avenue. One row for the window; individual "
        "unnamed calls are not invented.",
        f"{FSRI_VIA_LAT}",
    ),
    (
        "fr_morslay", "2025-01-07T23:20:00-08:00", "morslay_braeburn", STREET_M,
        "House on fire on Morslay Road (about 1/2 mile east of Lake Avenue); fire "
        "threatening a house on Braeburn Road in the same area.",
        f"{CITYGATE_PDF}, Table 4",
    ),
    (
        "fr_glenrose", "2025-01-07T23:49:00-08:00", "glenrose_loma_alta", STREET_M,
        "LACoFD battalion chief: structure fire at Glenrose Avenue and West Loma Alta "
        "Drive (west of Lake Avenue).",
        f"{CITYGATE_PDF}, Table 4; {FSRI_VIA_LAT}",
    ),
    (
        "fr_e_altadena_brush", "2025-01-08T00:35:00-08:00", "e_altadena_700", STREET_M,
        "Bushes on fire at 700 E Altadena Drive (west of Lake Avenue).",
        f"{CITYGATE_PDF}, Table 5",
    ),
    (
        "fr_las_flores", "2025-01-08T00:55:00-08:00", "las_flores_500", STREET_M,
        "LACoSD: house on fire at 500 E Las Flores Drive (west of Lake Avenue). First "
        "DINS-validated structure fire west of Lake in the McChrystal review.",
        f"{MCCHRYSTAL_PDF}; {CITYGATE_PDF}, Table 5",
    ),
    (
        "fr_upper_lake", "2025-01-08T01:30:00-08:00", "n_lake_loma_alta", STREET_ONLY_M,
        "Additional structure fires reported on or near upper Lake Avenue.",
        f"{CITYGATE_PDF}, Table 5",
    ),
    (
        "fr_farnsworth", "2025-01-08T02:18:00-08:00", "farnsworth_foothills", AREA_M,
        "LACoSD: fire in the foothills north of Farnsworth Park above Lake Avenue, "
        "moving west along the foothills.",
        f"{MCCHRYSTAL_PDF}; {CITYGATE_PDF}, Table 6",
    ),
    (
        "fr_monterosa", "2025-01-08T02:33:00-08:00", "monterosa_3400", STREET_M,
        "Pasadena PD: entire 3400 block of Monterosa Drive on fire (west of Lake Avenue, "
        "north of East Loma Alta Drive).",
        f"{CITYGATE_PDF}, Table 6",
    ),
    (
        "fr_wapello", "2025-01-08T02:43:00-08:00", "wapello_300", STREET_M,
        "LACoSD: fire coming near residences at 300 E Wapello Street (west of Lake Avenue, "
        "south of East Loma Alta Drive).",
        f"{CITYGATE_PDF}, Table 6",
    ),
    (
        "fr_fair_oaks", "2025-01-08T03:30:00-08:00", "fair_oaks_loma_alta", STREET_ONLY_M,
        "Multiple structure fires reported on Fair Oaks Avenue (west of Lake Avenue).",
        f"{CITYGATE_PDF}, Table 7",
    ),
    (
        "fr_front_crosses_lake", "2025-01-08T05:13:00-08:00", "concha_lake", STREET_ONLY_M,
        "Main fire front extended one block west of Lake Avenue between Concha Street "
        "and East Las Flores Drive (FireGuard).",
        f"{CITYGATE_PDF}, Finding #22",
    ),
]


def build() -> list[FireReport]:
    out: list[FireReport] = []
    for rid, when, place, precision, description, source in ROWS:
        lat, lon, _how = PLACES[place]
        t = parse_t(when)
        if t.utcoffset() is None:
            raise ValueError(f"{rid}: reported_at must include a UTC offset")
        out.append(FireReport(
            id=rid,
            lat=round(lat, 6),
            lon=round(lon, 6),
            h3=h3.latlng_to_cell(lat, lon, H3_RES),
            reported_at=t,
            description=description,
            location_precision_m=precision,
            source=source,
        ))
    return out


def main() -> None:
    reports = build()
    path = DATASETS["eaton"] / "fire_reports.jsonl"
    write_jsonl(path, reports)
    west = [r for r in reports if r.lon < -118.131466]
    print(f"Wrote {len(reports)} fire reports -> {path}")
    print(f"  {len(west)} west of Lake Avenue; first of those at "
          f"{west[0].reported_at.isoformat()}")
    print(f"  precision: {sorted({r.location_precision_m for r in reports})} m")


if __name__ == "__main__":
    main()
