"""Cited Eaton Fire places, the Lake Avenue divide, and the shared citations.

Times and wording come from the published investigations. Coordinates are US Census
geocoder matches for the named street or intersection, rounded to 6 dp. Evacuation alert
areas are not drawn here: build_evac_orders.py takes them from the real alerts.

Not loaded here: real 911 recordings, resident names, or house numbers that only
appear in redacted dispatch logs.
"""

from __future__ import annotations

# Lake Avenue at Altadena Drive (Census: 2260 N Lake Ave). Every "west of Lake" /
# "east of Lake" test uses this longitude.
LAKE_LON = -118.131466

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
LA_COUNTY_START = (
    "LA County, Eaton_Start_Location ('Location where the Eaton Fire Started'), "
    "https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services/Eaton_Start_Location/"
    "FeatureServer/34"
)
NBC = (
    "NBC News, 22 Jan 2025, "
    "https://www.nbcnews.com/news/us-news/eaton-fire-deaths-los-angeles-evacuation-orders-took-hours-rcna188729"
)

# Place key -> (lat, lon, how we got it). Intersections: Census onelineaddress.
PLACES: dict[str, tuple[float, float, str]] = {
    # Canyon origin is named, not a street. Precision is AREA_M wherever this is used.
    "eaton_canyon": (34.185961, -118.093668, "LA County Eaton Fire start location"),
    "altadena_dr_east": (34.176522, -118.098541, "Census: 1750 N Altadena Dr, Pasadena"),
    "kinneloa": (34.178904, -118.088622, "Census: 2000 Kinneloa Canyon Rd, Pasadena"),
    "hospital": (34.169086, -118.097360, "Census: 2580 E Washington Blvd, Pasadena"),
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


def west_of_lake(lon: float) -> bool:
    return lon < LAKE_LON
