"""Every assumed number in Outrun, in one place.

Real data describes the world that night (fire reports, satellites, roads, care facilities,
order times, which buildings burned). These numbers describe the *response* we simulate,
which never happened, so they cannot come from a record. Each one is labeled with where it
came from and the range the evaluation tests (docs/EVAL_SPEC.md), so no conclusion rests on
a single guess.

Status values:
- SOURCED: taken from a cited source.
- FROM_BRIEF: taken from the team's project brief.
- PLACEHOLDER: invented to make the code run. Must be sourced or swept before Oct 18.

Rules: engines import their constants from here; nobody hard-codes an assumed number
elsewhere; changing a value after the Oct 18 freeze is logged in docs/EVAL_SPEC.md.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Assumption:
    name: str
    value: object
    unit: str
    status: str  # SOURCED | FROM_BRIEF | PLACEHOLDER
    tested: str  # values the evaluation sweeps, or "" if not swept
    note: str


# --- Safety and deadlines -------------------------------------------------------------------

# Pickup deadline and driver safety use the same margin: a vehicle must LEAVE every hex
# (including a pickup address) at least this long before the fire's 10th-percentile arrival.
SAFETY_MARGIN_MIN = 30.0
ARRIVAL_PERCENTILE = 10  # "plausible" arrival = 10th percentile of the forecast
AT_RISK_P3H = 0.10  # route anyone with at least this chance of fire within 3 hours
HORIZON_MIN = 180.0  # forecast and planning horizon

# --- People ---------------------------------------------------------------------------------

# Which vehicle types can carry each need, and how long loading takes (minutes).
NEED_PROFILES: dict[str, tuple[list[str], float]] = {
    "wheelchair": (["wheelchair_van", "ambulance"], 12.0),  # 12 min: example in the brief
    "oxygen": (["ambulance", "wheelchair_van"], 15.0),  # placeholder
    "bedbound": (["ambulance"], 20.0),  # placeholder
    "no_car": (["bus", "wheelchair_van", "ambulance"], 5.0),  # placeholder
    "none": (["bus", "wheelchair_van", "ambulance"], 3.0),  # placeholder (not evaluated)
}
# Priority weights. Decide who goes first, so they need outside review (emergency manager or
# disability advocate) and are shown on screen.
VULNERABILITY = {"bedbound": 1.0, "oxygen": 0.9, "wheelchair": 0.8, "no_car": 0.6, "none": 0.2}

# --- Travel ---------------------------------------------------------------------------------

SPEED_FACTOR = 0.5  # share of normal road speed in smoke and traffic
STUB_SPEED_KMH = 30.0  # straight-line stub only: 0.5 x a 60 km/h road
DETOUR_FACTOR = 1.3  # straight-line stub only: roads are longer than straight lines
UNLOAD_MIN = 5.0  # time to unload at a shelter

# --- Who is known, and when (evaluation only) -----------------------------------------------

FRACTION_KNOWN = 0.25  # share of estimated residents on a list before the fire
NEVER_CALL = 0.0  # share of unknown residents who never call (0 = optimistic)
CALL_DELAY_MAX_MIN = 60.0  # a call comes uniformly 0..this long after the trigger
HANDLING_DELAY_MIN = 15.0  # time from a call to the planner seeing it (>= one 10-min replay step)
TRIGGER_KM = 2.0  # a published fire report or detection this close triggers a call

# --- Data publish delays (no hindsight) ------------------------------------------------------
# Data files hold only facts (when a satellite looked, when a model ran). These delays decide
# when each record became usable, applied when it is read (FireDetection / WindForecast).

FIRMS_LATENCY_MIN = 30.0  # VIIRS overpass -> detection published on FIRMS
GOES_LATENCY_MIN = 15.0  # GOES scan -> fire detection published
HRRR_PUBLISH_LAG_MIN = 60.0  # HRRR model run time -> forecast available

# --- Response (evaluation only) -------------------------------------------------------------

FLEET_BASELINE = {"wheelchair_van": 4, "ambulance": 4, "bus": 2}
APPROVAL_DELAY_MIN = 5.0  # plan made at t takes effect at t + this
ROAD_BLOCKAGE = 0.0  # share of road segments blocked (downed lines, debris)


REGISTER: list[Assumption] = [
    Assumption("Safety margin", SAFETY_MARGIN_MIN, "min", "PLACEHOLDER", "15, 30, 45",
               "Brief names a buffer but no number. Ask an emergency manager."),
    Assumption("Plausible arrival percentile", ARRIVAL_PERCENTILE, "%", "FROM_BRIEF", "5, 10",
               "arrival_p10_min in the brief's data format."),
    Assumption("At-risk threshold", AT_RISK_P3H, "P(fire in 3 h)", "PLACEHOLDER", "",
               "Who the router must route or escalate."),
    Assumption("Loading times", NEED_PROFILES, "min", "PLACEHOLDER", "x0.5, x1, x2",
               "Wheelchair 12 min is from the brief; others need published boarding times."),
    Assumption("Vulnerability weights", VULNERABILITY, "", "PLACEHOLDER", "",
               "Triage rule: needs outside review before Oct 18."),
    Assumption("Speed factor", SPEED_FACTOR, "x road speed", "PLACEHOLDER", "0.25, 0.5, 0.75",
               "Source candidate: evacuation traffic studies."),
    Assumption("Fraction known in advance", FRACTION_KNOWN, "", "PLACEHOLDER",
               "0, 0.25, 0.5, 1", "No registry enrollment source found yet."),
    Assumption("Never call", NEVER_CALL, "", "PLACEHOLDER", "0, 0.10, 0.25",
               "0 is the optimistic case."),
    Assumption("Call delay after trigger", CALL_DELAY_MAX_MIN, "min (max of uniform)",
               "PLACEHOLDER", "30, 60", ""),
    Assumption("Call handling delay", HANDLING_DELAY_MIN, "min", "PLACEHOLDER", "5, 15, 30", ""),
    Assumption("Call trigger distance", TRIGGER_KM, "km", "PLACEHOLDER", "1, 2, 3", ""),
    Assumption("Fleet", FLEET_BASELINE, "vehicles", "PLACEHOLDER", "2, 5, 10, 20, 40, 80",
               "Source candidates: county reviews (Pasadena transit buses), paratransit fleets."),
    Assumption("Approval delay", APPROVAL_DELAY_MIN, "min", "PLACEHOLDER", "0, 5, 10, 20",
               "Ask an emergency manager."),
    Assumption("Road blockage", ROAD_BLOCKAGE, "share of segments", "PLACEHOLDER",
               "0, 0.05, 0.10", "Needs the road network."),
    Assumption("Unload time", UNLOAD_MIN, "min", "PLACEHOLDER", "", ""),
    Assumption("FIRMS publish delay", FIRMS_LATENCY_MIN, "min", "PLACEHOLDER", "15, 30, 180",
               "Decides whether satellite data arrives before the 03:25 orders (Daniel)."),
    Assumption("GOES publish delay", GOES_LATENCY_MIN, "min", "PLACEHOLDER", "5, 15, 30", ""),
    Assumption("HRRR publish delay", HRRR_PUBLISH_LAG_MIN, "min", "PLACEHOLDER", "45, 60, 90",
               "Typical operational latency 45-60 min; verify."),
]
