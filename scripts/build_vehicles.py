"""Build data/processed/eaton/vehicles.jsonl: the rescue fleet, starting at a real yard.

What is sourced:
- 11 buses: Pasadena Transit's general manager staffed 11 buses that night and sent them to
  senior care facilities (LAist, CBS Los Angeles; the county review confirms Pasadena Transit
  buses were mobilized). Each is a 35-foot New Flyer Xcelsior (the model Pasadena bought):
  32 seats and 2 wheelchair spaces (New Flyer brochure, 2021).
- Wheelchair vans: Pasadena Dial-A-Ride cutaways, "up to 16 passengers and four wheelchair
  securements" (City of Pasadena, Apr 8, 2024). With all four securements in use, 6 seats
  remain, so each van is 6 seats + 4 wheelchair spaces.
- The yard: Pasadena Transit's operations and maintenance facility, 303 N Allen Ave
  (Census geocoder). Dial-A-Ride is run under the same Pasadena Transit contract.

What is assumed (backend/assumptions.py FLEET_BASELINE, swept in the evaluation):
- How many vans and ambulances were free that night: no source gives a number, so these use
  the evaluation spec's baseline (4 and 4).
- The ambulances start at the same yard, and carry 1 stretcher, 1 wheelchair and 2 seated.

    uv run python scripts/build_vehicles.py
"""

from __future__ import annotations

from backend.assumptions import FLEET_BASELINE, VEHICLE_SPECS
from backend.schemas import Vehicle
from backend.store import DATASETS, write_jsonl

YARD = "pasadena_transit_yard"  # 303 N Allen Ave, Pasadena
YARD_LAT, YARD_LON = 34.150791, -118.113256



def build() -> list[Vehicle]:
    out = []
    for kind, count in FLEET_BASELINE.items():
        prefix, seats, wheelchair, stretcher = VEHICLE_SPECS[kind]
        out += [
            Vehicle(id=f"{prefix}_{n:02d}", type=kind, seats=seats,
                    wheelchair_spaces=wheelchair, stretcher_spaces=stretcher,
                    lat=YARD_LAT, lon=YARD_LON, depot=YARD)
            for n in range(1, count + 1)
        ]
    return out


def main() -> None:
    vehicles = build()
    out = DATASETS["eaton"] / "vehicles.jsonl"
    write_jsonl(out, vehicles)
    print(f"Wrote {len(vehicles)} vehicles -> {out}")
    for kind, count in FLEET_BASELINE.items():
        print(f"  {count:>2} {kind}")


if __name__ == "__main__":
    main()
