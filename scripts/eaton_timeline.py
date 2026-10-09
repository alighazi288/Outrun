"""Cited Eaton Fire places, the Lake Avenue divide, and reconstructed order polygons.

Times, zone ids and wording come from the published investigations. Coordinates are
US Census geocoder matches for the named street or intersection, rounded to 6 dp.
Official Genasys shapefiles are not in this repo: order polygons are street-bounded
boxes from those same named streets (Lake Avenue as the east/west split the reports use).

Not loaded here: real 911 recordings, resident names, or house numbers that only
appear in redacted dispatch logs.
"""

from __future__ import annotations

# Lake Avenue at Altadena Drive (Census: 2260 N Lake Ave). Every "west of Lake" /
# "east of Lake" test uses this longitude.
LAKE_LON = -118.131466

# Study-area box from data/processed/eaton/meta.json (Altadena CDP + 1 km).
BOX = {"south": 34.1585, "west": -118.1826, "north": 34.2264, "east": -118.0841}

# How precisely a published record locates fire (data/BUILD.md).
STREET_M = 250.0   # a named intersection or hundred-block
STREET_ONLY_M = 500.0  # a named street, no block
AREA_M = 1000.0    # a canyon, flank, or "west of the origin"

CITYGATE_PDF = (
    "Citygate, Investigation Report of the Eaton Fire Evacuation Alerts, "
    "18 May 2026 (errata 19 May), "
    "https://file.lacounty.gov/SDSInter/lac/1208708_InvestigationReportoftheEatonFireEvacuationAlerts_05-18-26_.pdf"
)
MCCHRYSTAL_PDF = (
    "McChrystal Group, After-Action Review of Alert Notification Systems and "
    "Evacuation Policies for the Eaton and Palisades Fires, "
    "https://file.lacounty.gov/SDSInter/lac/1192777_AAR_EatonFireSynopsisofFindingsandTimeline.pdf"
)
FSRI_REPORT = (
    "FSRI, Southern California Fires Timeline Report, 20 Nov 2025, "
    "https://fsri.org/research-update/southern-california-fires-timeline-report"
)
FSRI_VIA_LAT = (
    f"{FSRI_REPORT}; locations named in Los Angeles Times, 20 Nov 2025, "
    "https://www.latimes.com/california/story/2025-11-20/state-report-alarms-eaton-fire-evacuations"
)
NBC = (
    "NBC News, 22 Jan 2025, "
    "https://www.nbcnews.com/news/us-news/eaton-fire-deaths-los-angeles-evacuation-orders-took-hours-rcna188729"
)

# Place key -> (lat, lon, how we got it). Intersections: Census onelineaddress.
PLACES: dict[str, tuple[float, float, str]] = {
    # Canyon origin is named, not a street. Precision is AREA_M wherever this is used.
    "eaton_canyon": (34.2040, -118.0960, "Eaton Canyon north of Altadena (investigations)"),
    "altadena_dr_east": (34.176522, -118.098541, "Census: 1750 N Altadena Dr, Pasadena"),
    "kinneloa": (34.178904, -118.088622, "Census: 2000 Kinneloa Canyon Rd, Pasadena"),
    "hospital": (34.169086, -118.097360, "Census: 2580 E Washington Blvd, Pasadena"),
    "west_of_origin": (34.2040, -118.1070, "1 km west of the named Eaton Canyon origin"),
    "toward_lake": (34.204044, -118.1200, "Between origin and N Lake Ave & E Loma Alta Dr"),
    "n_lake_loma_alta": (34.204044, -118.130690, "Census: N Lake Ave & E Loma Alta Dr"),
    "midwick_glen_canyon": (34.182888, -118.106120, "Census: Midwick Dr & Glen Canyon Rd"),
    "mendocino_midlothian": (34.187089, -118.107903, "Census: N Midlothian Dr & E Mendocino St"),
    "morslay_braeburn": (34.187555, -118.113251, "Census: Morslay Rd & Braeburn Rd"),
    "glenrose_loma_alta": (34.202771, -118.147337, "Census: Glenrose Ave & W Loma Alta Dr"),
    "e_altadena_700": (34.190396, -118.134521, "Census: 700 E Altadena Dr, Altadena"),
    "las_flores_500": (34.196230, -118.135217, "Census: 500 E Las Flores Dr, Altadena"),
    "mount_curve_lake": (34.201108, -118.130775, "Census: E Mount Curve Ave & N Lake Ave"),
    "farnsworth_foothills": (34.2080, -118.1315, "North of Farnsworth Park above Lake Ave"),
    "monterosa_3400": (34.202705, -118.133004, "Census: 3400 Monterosa Dr, Altadena"),
    "wapello_300": (34.200534, -118.137682, "Census: 300 E Wapello St, Altadena"),
    "fair_oaks_loma_alta": (34.203069, -118.143396, "Census: N Fair Oaks Ave & W Loma Alta Dr"),
    "concha_lake": (34.199129, -118.130883, "Census: N Lake Ave & Concha St"),
    "las_flores_lake": (34.195011, -118.131081, "Census: N Lake Ave & E Las Flores Dr"),
    "lincoln_altadena": (34.198279, -118.159000, "Census: N Lincoln Ave & W Altadena Dr"),
    "lake_woodbury": (34.177066, -118.131884, "Census: N Lake Ave & E Woodbury Rd"),
}


def box(west: float, south: float, east: float, north: float) -> list[list[float]]:
    """Closed GeoJSON ring, [lon, lat] pairs."""
    return [
        [west, south], [east, south], [east, north], [west, north], [west, south],
    ]


def west_of_lake(lon: float) -> bool:
    return lon < LAKE_LON


# Reconstructed covering polygons (not official Genasys shapefiles).
# South edge ~ Washington Blvd / CDP; north ~ foothills; split on Lake Avenue.
# Earlier polygons must not contain zones ordered later: first_trigger / warned_at
# take the earliest covering ring, not the matching zone_id.
_SOUTH, _NORTH = 34.1689, 34.2150
MOUNT_LOWE_EAST = round(LAKE_LON + 0.008, 6)  # ~730 m east of Lake
MOUNT_LOWE_SOUTH, MOUNT_LOWE_NORTH = 34.1780, 34.2100
# Immediately east of Lake (Citygate: ALD-MOUNTLOWE, 7:55 p.m. warning / 9:00 p.m. order).
MOUNT_LOWE = box(LAKE_LON, MOUNT_LOWE_SOUTH, MOUNT_LOWE_EAST, MOUNT_LOWE_NORTH)
# 6:48 / 7:26 east-of-Lake zones, excluding the Mount Lowe strip.
EAST_ALTADENA = box(MOUNT_LOWE_EAST, _SOUTH, BOX["east"], _NORTH)
EAST_LAKE_SOUTH = box(LAKE_LON, _SOUTH, MOUNT_LOWE_EAST, MOUNT_LOWE_SOUTH)
EAST_LAKE_NORTH = box(LAKE_LON, MOUNT_LOWE_NORTH, MOUNT_LOWE_EAST, _NORTH)
WEST_ALTADENA = box(BOX["west"], _SOUTH, LAKE_LON, _NORTH)
KINNELOA = box(-118.1000, 34.1680, BOX["east"], 34.1950)
# Pasadena zones south of Woodbury, still inside the 1 km study margin.
PASADENA_NORTH = box(LAKE_LON, BOX["south"], -118.0900, 34.1771)
# JPL / La Cañada, issued with the 3:25 a.m. west-Altadena batch.
JPL = box(BOX["west"], 34.1900, -118.1650, 34.2150)
