"""How Census counts become people who may need a ride. One rule for every area: the Altadena
build (scripts/build_residents.py) and any area set up on demand (backend/area.py).

Counts come from the Census ACS 5-year tables per tract; the shares that turn them into needs
are labeled assumptions in backend/assumptions.py:

    wheelchair  people with an ambulatory difficulty (B18105) x WHEELCHAIR_SHARE_OF_AMBULATORY
    bedbound    people 65+ (B01001) x BEDBOUND_SHARE_65
    oxygen      people 65+ (B01001) x OXYGEN_SHARE_65
    no_car      households with no vehicle, by household size (B08201): one row per household

Variable names use the ACS summary-file style, e.g. "B18105_E004".
"""

from __future__ import annotations

import math

from backend.assumptions import BEDBOUND_SHARE_65, OXYGEN_SHARE_65, WHEELCHAIR_SHARE_OF_AMBULATORY

# People with an ambulatory difficulty, all ages 5+ (male, then female).
AMBULATORY = [f"B18105_E{n:03d}" for n in (4, 7, 10, 13, 16, 20, 23, 26, 29, 32)]
AGE_65 = [f"B01001_E{n:03d}" for n in (*range(20, 26), *range(44, 50))]  # 65+, male and female
# Households with no vehicle, by size (4 = four or more).
NO_CAR_BY_SIZE = {1: "B08201_E008", 2: "B08201_E014", 3: "B08201_E020", 4: "B08201_E026"}
TOTAL_POPULATION = "B01001_E001"
VARIABLES = [TOTAL_POPULATION, *AMBULATORY, *AGE_65, *NO_CAR_BY_SIZE.values()]


def api_name(variable: str) -> str:
    """Summary-file "B18105_E004" -> Census API "B18105_004E"."""
    table, number = variable.split("_E")
    return f"{table}_{number}E"


def tract_needs(acs: dict[str, int]) -> dict[tuple[str, int], float]:
    """Expected number of people (need, household size) in one tract."""
    ambulatory = sum(acs[v] for v in AMBULATORY)
    age_65 = sum(acs[v] for v in AGE_65)
    out = {
        ("wheelchair", 1): ambulatory * WHEELCHAIR_SHARE_OF_AMBULATORY,
        ("bedbound", 1): age_65 * BEDBOUND_SHARE_65,
        ("oxygen", 1): age_65 * OXYGEN_SHARE_65,
    }
    for size, var in NO_CAR_BY_SIZE.items():
        out[("no_car", size)] = acs[var]
    return out


def allocate(n: int, shares: dict[str, float]) -> list[str]:
    """n items split by shares, largest remainder first: the counts always add up to n."""
    exact = {k: n * v / sum(shares.values()) for k, v in shares.items()}
    counts = {k: math.floor(v) for k, v in exact.items()}
    short = n - sum(counts.values())
    for k in sorted(exact, key=lambda k: exact[k] - counts[k], reverse=True)[:short]:
        counts[k] += 1
    return [k for k in shares for _ in range(counts[k])]
