"""Build data/processed/eaton/shelters.jsonl: the evacuation centers open to Eaton evacuees.

Hand-collected from official timelines and CAL FIRE incident updates, one citation each.

opened_at is the earliest time a source puts the shelter in use or on an official list: for
Pasadena the city's decision to open it (doors likely opened a little later), for Arcadia the
first official listing (it may have opened earlier).

What the sources say about the fire night:
- Pasadena's own timeline: "8:00 pm: Convention Center agrees to host evacuation center".
- CAL FIRE's updates at 12:03, 4:50 and 5:16 a.m. Jan 8 list it as the only Eaton shelter
  (their other two, in Woodland Hills and Westwood, were for the Palisades Fire, 35+ km away).
- Arcadia Community Center first appears in CAL FIRE's 2:55 p.m. Jan 8 update: after the
  replay ends, so it never shows up in it. Kept so the list is complete if the window grows.
- Pomona Fairplex appears only in lists updated days later, with no opening time: left out.

Capacity is not published, so it is left empty (nothing in the planner uses it yet).
Coordinates: OpenStreetMap building outlines (the Census geocoder put 300 E Green St on
W Green St, 1 km off).

    uv run python scripts/build_shelters.py
"""

from __future__ import annotations

from datetime import datetime

from backend.schemas import Shelter
from backend.store import DATASETS, write_jsonl

PASADENA_TIMELINE = (
    "City of Pasadena, City Council presentation Jan 13, 2025 (agenda item AR 3), timeline: "
    "'8:00 pm: Convention Center agrees to host evacuation center', "
    "https://ww2.cityofpasadena.net/2025%20Agendas/Jan_13_25/AR%203%20PPT.pdf"
)
CAL_FIRE_0255PM = (
    "CAL FIRE Eaton Fire incident update 01/08/2025 2:55 PM, Evacuation Shelters, "
    "https://www.fire.ca.gov/incidents/2025/1/7/eaton-fire/updates/"
    "74cee001-c0c2-4c15-9aee-f7a677402228"
)

SHELTERS = [
    Shelter(
        id="shelter_pasadena_convention_center",
        name="Pasadena Convention Center, 300 E Green St, Pasadena",
        lat=34.14365, lon=-118.14521,
        opened_at=datetime.fromisoformat("2025-01-07T20:00:00-08:00"),
        source=PASADENA_TIMELINE,
    ),
    Shelter(
        id="shelter_arcadia_community_center",
        name="Arcadia Community Center, 375 Campus Dr, Arcadia",
        lat=34.13122, lon=-118.04529,
        opened_at=datetime.fromisoformat("2025-01-08T14:55:00-08:00"),
        source=CAL_FIRE_0255PM,
    ),
]


def main() -> None:
    out = DATASETS["eaton"] / "shelters.jsonl"
    write_jsonl(out, SHELTERS)
    print(f"Wrote {len(SHELTERS)} shelters -> {out}")
    for s in SHELTERS:
        print(f"  opens {s.opened_at:%b %d %H:%M}  {s.name}")


if __name__ == "__main__":
    main()
