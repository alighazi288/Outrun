"""Build data/processed/eaton/facilities.jsonl: the real licensed care facilities in the area.

Two public sources (California Health and Human Services open data portal):
- Community Care Licensing (CCL): residential care for the elderly and adult residential
  facilities. Every license ever issued, with its first and closed dates.
- CDPH Licensed Healthcare Facility Listing, December 31, 2024: skilled nursing, congregate
  living health and intermediate care facilities, one week before the fire.

No hindsight: a facility counts if it was licensed ON THE FIRE NIGHT (Jan 7, 2025). Filtering
on today's status would drop the homes that closed after the fire, the ones that matter most.
Overnight residents only: adult DAY programs are out (the fire came at night). Children's
residential care is out for now (a team decision to revisit). Personal details in the source
(administrator, licensee, phone) are never copied.

CCL rows have addresses but no coordinates, so they are looked up in one batch request to the
US Census Bureau geocoder. Rows it can't match are listed, never dropped silently.

    uv run python scripts/build_facilities.py
"""

from __future__ import annotations

import csv
import io
import json
import string
import urllib.request
import uuid
from datetime import date

import h3

from backend.schemas import H3_RES, Facility
from backend.store import DATA_DIR, DATASETS, write_jsonl

FIRE_DATE = date(2025, 1, 7)
RAW = DATA_DIR / "raw" / "ccl"
CKAN = "https://data.chhs.ca.gov/api/3/action/package_show?id="
SOURCES = {  # local file -> (dataset, resource name on the portal)
    "rcfe.csv": ("ccl-facilities", "Residential Care Facilities for the Elderly"),
    "arf.csv": ("ccl-facilities", "Adult Residential Facilities"),
    "cdph_2024-12-31.csv": ("licensed-healthcare-facility-listing",
                            "Licensed Healthcare Facility Listing, December 31, 2024"),
}
# CCL facility types where people live overnight (adult day programs are left out).
CCL_TYPES = {
    "RESIDENTIAL CARE ELDERLY": "residential care for the elderly",
    "RCFE-CONTINUING CARE RETIREMENT COMMUNITY": "continuing care retirement community",
    "ADULT RESIDENTIAL": "adult residential facility",
    "ADULT RESIDENTIAL FACILITY FOR PERSONS WITH SPECIAL HEALTH CARE NEEDS":
        "adult residential facility, special health care needs",
    "RESIDENTIAL FACILITY CHRONICALLY ILL": "residential facility for the chronically ill",
    "SOCIAL REHABILITATION FACILITY": "social rehabilitation facility",
    "COMMUNITY CRISIS HOME - ARF": "community crisis home",
    "ENHANCED BEHAVIORAL SUPPORTS HOME - ARF": "enhanced behavioral supports home",
}
# CDPH license categories where people live overnight (hospitals have their own plans).
CDPH_TYPES = ("Skilled Nursing Facility", "Congregate Living Health Facility",
              "Intermediate Care Facility", "Hospice Facility")
# Cities touching the study area. Only candidates: the study-area box decides.
NEARBY_CITIES = {"ALTADENA", "PASADENA", "SIERRA MADRE", "LA CANADA FLINTRIDGE", "ARCADIA",
                 "SAN MARINO", "SOUTH PASADENA"}
CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


def download() -> None:
    """Fetch each source once into data/raw/ccl/ (git ignores data/raw)."""
    RAW.mkdir(parents=True, exist_ok=True)
    for filename, (dataset, resource) in SOURCES.items():
        if (RAW / filename).exists():
            continue
        with urllib.request.urlopen(CKAN + dataset, timeout=60) as response:
            resources = json.load(response)["result"]["resources"]
        url = next(r["url"] for r in resources if r["name"].strip() == resource)
        with urllib.request.urlopen(url, timeout=300) as response:  # follows the redirect
            (RAW / filename).write_bytes(response.read())
        print(f"Downloaded {resource} -> {RAW / filename}")


def _date(text: str) -> date | None:
    text = text.strip()
    if not text:
        return None
    month, day, year = (int(x) for x in text.split("/"))
    return date(year, month, day)


def licensed_on(row: dict, day: date) -> bool:
    """Licensed on `day`: first licensed by then, and not closed before or on it."""
    first, closed = _date(row["license_first_date"]), _date(row["closed_date"])
    return first is not None and first <= day and (closed is None or closed > day)


def ccl_candidates() -> list[dict]:
    rows = []
    for name in ("rcfe.csv", "arf.csv"):
        with (RAW / name).open(encoding="utf-8-sig") as f:
            rows += list(csv.DictReader(f))
    return [
        r for r in rows
        if r["county_name"].strip().upper() == "LOS ANGELES"
        and r["facility_city"].strip().upper() in NEARBY_CITIES
        and r["facility_type"].strip() in CCL_TYPES
        and licensed_on(r, FIRE_DATE)
    ]


def geocode_batch(rows: list[dict]) -> dict[str, tuple[float, float]]:
    """facility_number -> (lat, lon), from one Census batch request."""
    lines = io.StringIO()
    writer = csv.writer(lines)
    for r in rows:
        writer.writerow([r["facility_number"], r["facility_address"], r["facility_city"],
                         "CA", r["facility_zip"][:5]])
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"benchmark\"\r\n\r\n"
        f"Public_AR_Current\r\n--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"addressFile\"; filename=\"addresses.csv\"\r\nContent-Type: text/csv\r\n\r\n"
        f"{lines.getvalue()}\r\n--{boundary}--\r\n"
    ).encode()
    request = urllib.request.Request(
        CENSUS_BATCH, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        text = response.read().decode()
    found = {}
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 6 and row[2] == "Match":
            lon, lat = (float(x) for x in row[5].split(","))
            found[row[0]] = (lat, lon)
    return found


def build() -> tuple[list[Facility], list[str]]:
    """The facilities inside the study area, and the CCL rows the geocoder couldn't place."""
    box = json.loads((DATASETS["eaton"] / "meta.json").read_text())["bbox"]

    def inside(lat: float, lon: float) -> bool:
        return box["south"] <= lat <= box["north"] and box["west"] <= lon <= box["east"]

    out: list[Facility] = []
    candidates = ccl_candidates()
    where = geocode_batch(candidates)
    unmatched = []
    for r in candidates:
        if r["facility_number"] not in where:
            unmatched.append(f"{r['facility_name']}, {r['facility_address']}, {r['facility_city']}")
            continue
        lat, lon = where[r["facility_number"]]
        if not inside(lat, lon):
            continue
        closed = r["closed_date"].strip() or "still open"
        out.append(Facility(
            id=f"ccl_{r['facility_number']}",
            name=string.capwords(r["facility_name"].strip().lower()),
            kind=CCL_TYPES[r["facility_type"].strip()], lat=round(lat, 6), lon=round(lon, 6),
            h3=h3.latlng_to_cell(lat, lon, H3_RES),
            licensed_capacity=int(r["facility_capacity"] or 0),
            source=f"CA Community Care Licensing, data.chhs.ca.gov, license {r['facility_number']}"
                   f" (licensed {r['license_first_date']}, closed: {closed}); location: US "
                   "Census geocoder",
        ))

    with (RAW / "cdph_2024-12-31.csv").open(encoding="utf-8-sig", errors="replace") as f:
        for r in csv.DictReader(f):
            kind = r["LICENSE_CATEGORY_DESC"].strip()
            if not kind.startswith(CDPH_TYPES) or r["FACILITY_STATUS_DESC"].strip() != "Open":
                continue
            try:
                lat, lon = float(r["LATITUDE"]), float(r["LONGITUDE"])
            except ValueError:
                continue
            if not inside(lat, lon):
                continue
            out.append(Facility(
                id=f"cdph_{r['LICENSE_NUM'].strip()}",
                name=string.capwords(r["FACILITY_NAME"].strip().lower()),
                kind=kind.lower(), lat=round(lat, 6), lon=round(lon, 6),
                h3=h3.latlng_to_cell(lat, lon, H3_RES),
                licensed_capacity=int(float(r["TOTAL_NUMBER_BEDS"] or 0)),
                source="CDPH Licensed Healthcare Facility Listing, December 31, 2024, "
                       f"data.chhs.ca.gov, license {r['LICENSE_NUM'].strip()}",
            ))
    return sorted(out, key=lambda f: f.id), unmatched


def main() -> None:
    download()
    facilities, unmatched = build()
    out = DATASETS["eaton"] / "facilities.jsonl"
    write_jsonl(out, facilities)
    beds = sum(f.licensed_capacity for f in facilities)
    print(f"Wrote {len(facilities)} facilities ({beds:,} licensed places) -> {out}")
    by_kind: dict[str, int] = {}
    for f in facilities:
        by_kind[f.kind] = by_kind.get(f.kind, 0) + 1
    for kind, n in sorted(by_kind.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {kind}")
    if unmatched:
        print(f"\nThe Census geocoder couldn't place {len(unmatched)} licensed facilities "
              "(check by hand; they may be inside the area):")
        for line in unmatched:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
