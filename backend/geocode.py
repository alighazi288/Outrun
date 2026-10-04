"""Address -> (lat, lon), so agents never write coordinates themselves.

Uses the US Census Bureau geocoder: no key, public domain. It needs a house number and
street ("2260 N Lake Ave, Altadena, CA"); a street name alone finds nothing, and the Intake
agent then asks the caller for the number or the nearest address.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"


def census_geocode(address: str) -> tuple[float, float] | None:
    """(lat, lon) of the best match, or None if the address isn't found."""
    query = urllib.parse.urlencode(
        {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
    )
    with urllib.request.urlopen(f"{CENSUS_URL}?{query}", timeout=15) as response:
        matches = json.load(response)["result"]["addressMatches"]
    if not matches:
        return None
    point = matches[0]["coordinates"]  # x = longitude, y = latitude
    return point["y"], point["x"]
