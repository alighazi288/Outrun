"""Shared data contracts. Every component speaks these types.

Engines, API, pipeline, evaluation, dashboard and Orchestrate agents all read and write
these models. If you change a field, tell the team and re-run `scripts/export_openapi.py`
so the frontend and agents see the change.

Conventions
- Times are timezone-aware ISO-8601 in Pacific time, e.g. "2025-01-07T23:40:00-08:00".
  Naive datetimes are rejected on purpose (they cause silent hindsight bugs).
- Map cells are Uber H3 at resolution 9 (roughly one city block), as hex strings.
- Durations are minutes. Distances are metres. Probabilities are 0..1.
- Locked on 2026-10-05. Changing a field now needs a heads-up to the team first.
- Data files hold facts only. Assumed publish delays (backend/assumptions.py) are applied when
  a record is read, so the evaluation can test other delays without rebuilding files.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from backend.assumptions import (
    FIRMS_LATENCY_MIN,
    GOES_LATENCY_MIN,
    HRRR_PUBLISH_LAG_MIN,
    NEED_PROFILES,  # noqa: F401  (re-exported for callers)
)

H3_RES = 9

Need = Literal["wheelchair", "oxygen", "bedbound", "no_car", "none"]
VehicleType = Literal["wheelchair_van", "ambulance", "bus"]
VehicleStatus = Literal["idle", "en_route", "loading"]
# Where a resident record comes from:
#   facility   lives in a real licensed care facility (known from the start)
#   estimated  placed from Census counts (real addresses aren't public); population files use
#              this, and backend/knowledge.py turns each into "registry" or "call"
#   registry   estimated, and on a list before the fire (known from the start)
#   call       estimated, known only once their simulated help call arrives (known_at)
#   request    entered live through POST /requests (the Intake agent, in the demo)
ResidentSource = Literal["facility", "estimated", "registry", "call", "request"]
# Vehicle types and loading times per need live in backend/assumptions.py (NEED_PROFILES), so
# every assumed number sits in one labeled place and an LLM never picks them.


class Model(BaseModel):
    """Base for all contracts: unknown fields are an error, not silently dropped."""

    model_config = ConfigDict(extra="forbid")

    def visible_from(self) -> datetime | None:
        """When this record first existed in the real world. None = known before the fire.

        `clock.as_of()` hides a record until `t >= visible_from()`. This is how we guarantee
        no hindsight.
        """
        return None


# --------------------------------------------------------------------------------------
# The brief's five shared formats
# --------------------------------------------------------------------------------------


class Resident(Model):
    """One person who may need help evacuating. Care-facility residents come from real licensed
    facilities; everyone else is estimated from Census counts (real addresses are not public)."""

    id: str = Field(examples=["r_0412"])
    lat: float
    lon: float
    h3: str = Field(description="H3 res-9 cell containing the home")
    needs: Need
    vehicle_types: list[VehicleType] = Field(description="Vehicle types that can carry them")
    load_minutes: float = Field(ge=0, description="Time to get them into a vehicle")
    people: int = Field(1, ge=1, description="People travelling together, including carers")
    source: ResidentSource = "registry"
    # When the system first learned about this person (requests arrive mid-fire).
    known_at: AwareDatetime | None = None
    # Free-text details from a help request, e.g. "2nd floor, no elevator".
    notes: str | None = None
    # The care facility this resident lives in, if any.
    facility_id: str | None = None
    # The address a help request gave (estimated residents have none: real addresses are
    # never used).
    address: str | None = None

    def visible_from(self) -> datetime | None:
        return self.known_at


class Vehicle(Model):
    """One vehicle in the rescue fleet."""

    id: str = Field(examples=["v_03"])
    type: VehicleType
    seats: int = Field(ge=0)
    wheelchair_spaces: int = Field(0, ge=0)
    # Bedbound residents travel on a stretcher, which is its own space.
    stretcher_spaces: int = Field(0, ge=0)
    lat: float
    lon: float
    status: VehicleStatus = "idle"
    # The depot this vehicle starts from.
    depot: str | None = None
    # Minutes after t until the vehicle is free (it finishes its current run first,
    # and no new plan takes effect before it is approved). The router starts its clock here.
    available_in_min: float = Field(0.0, ge=0)


class FireOutlook(Model):
    """Fire forecast for one map cell at time t. Produced by the nowcast engine."""

    t: AwareDatetime
    h3: str
    p_1h: float = Field(ge=0, le=1, description="P(fire reaches this cell within 1 hour)")
    p_2h: float = Field(ge=0, le=1)
    p_3h: float = Field(ge=0, le=1)
    arrival_p10_min: float | None = Field(
        None,
        description=(
            "Pessimistic arrival: 10% chance the fire arrives sooner than this many minutes "
            "after t. None = not expected within the forecast horizon."
        )
    )
    # Fire evidence (a detection or report) covers this cell at or before t.
    burning: bool = False

    @model_validator(mode="after")
    def _monotone(self) -> FireOutlook:
        if not (self.p_1h <= self.p_2h <= self.p_3h):
            raise ValueError("probabilities must satisfy p_1h <= p_2h <= p_3h")
        return self


class Route(Model):
    """One vehicle's ordered stops. Stops are resident ids and shelter ids."""

    vehicle: str
    stops: list[str]
    eta_min: list[float] = Field(description="Minutes after t until arrival at each stop")

    @model_validator(mode="after")
    def _same_length(self) -> Route:
        if len(self.stops) != len(self.eta_min):
            raise ValueError("stops and eta_min must have the same length")
        return self


class Plan(Model):
    """Output of the route optimizer at time t."""

    t: AwareDatetime
    plan_id: str = Field(examples=["p_20250107T2340"])
    routes: list[Route]
    unreachable: list[str] = Field(
        description="At-risk residents no vehicle can reach in time. Escalated, never dropped."
    )
    reasons: dict[str, str] = Field(
        description="Plain-language reason per resident, filled in from engine numbers"
    )
    escalated_fire_command: list[str] = Field(
        default_factory=list,
        description="Subset of unreachable: too late, or only reachable through danger. These "
        "go to fire command (from docs/ARCHITECTURE.md).",
    )
    # Which engine produced this plan (stub, OR-Tools, a baseline...).
    strategy: str = "closest_first_stub"


class PlanChange(Model):
    """One edit a human made to a plan."""

    kind: Literal["reassign", "remove_stop", "add_stop", "hold_vehicle"]
    resident: str | None = None
    vehicle: str | None = None
    note: str | None = None


class Decision(Model):
    """What the emergency manager did with a plan."""

    plan_id: str
    action: Literal["approve", "modify", "reject"]
    by: str = "emergency_manager"
    t: AwareDatetime
    changes: list[PlanChange] = []
    # Why the human changed or rejected it (goes in the decision log).
    reason: str | None = None

    def visible_from(self) -> datetime | None:
        return self.t


# --------------------------------------------------------------------------------------
# Input records and glue types the engines need
# --------------------------------------------------------------------------------------


class FireDetection(Model):
    """One satellite fire detection (NASA FIRMS VIIRS, NOAA GOES)."""

    id: str
    lat: float
    lon: float
    h3: str
    observed_at: AwareDatetime = Field(description="When the satellite looked (overpass or scan)")
    available_at: AwareDatetime | None = Field(
        None,
        description=(
            "When the detection was published, ONLY if the source records it. Leave empty and "
            "the assumed publish delay for its satellite (backend/assumptions.py) is applied."
        ),
    )
    source: str = Field(
        "VIIRS_SNPP",
        description="Satellite and instrument: VIIRS_SNPP, VIIRS_NOAA20, VIIRS_NOAA21, GOES18...",
    )
    pixel_m: float = Field(
        375.0, gt=0,
        description="Pixel size, metres: about 375 for VIIRS, about 2000 for GOES. The fire is "
        "somewhere inside it.",
    )
    frp_mw: float | None = Field(None, description="Fire radiative power, megawatts")
    confidence: Literal["low", "nominal", "high"] | None = Field(
        None, description="VIIRS l/n/h map to low/nominal/high"
    )

    def visible_from(self) -> datetime | None:
        if self.available_at is not None:
            return self.available_at
        return self.observed_at + timedelta(minutes=publish_delay_min(self.source))


def publish_delay_min(source: str) -> float:
    """Assumed minutes from observation to publication for a detection source."""
    return GOES_LATENCY_MIN if source.upper().startswith("GOES") else FIRMS_LATENCY_MIN


class FireReport(Model):
    """One report of fire at a place and time: a 911 call or radio report in live use; in the
    Eaton replay, a timestamped report from the published investigations (FSRI, county review).
    Reports were the main real-time signal that night: the VIIRS satellite's first detection of
    the fire was at 1:30 a.m."""

    id: str
    lat: float
    lon: float
    h3: str
    reported_at: AwareDatetime = Field(description="When the report reached dispatch")
    description: str = Field(description="What was reported, in words")
    location_precision_m: float = Field(
        250.0, ge=0, description="How precisely the published record locates it"
    )
    source: str = Field(description="Citation (investigation report and page) or 'intake'")

    def visible_from(self) -> datetime | None:
        return self.reported_at


class Facility(Model):
    """A real licensed care facility (California Community Care Licensing data)."""

    id: str
    name: str
    kind: str = Field(description="License type, e.g. residential care for the elderly")
    lat: float
    lon: float
    h3: str
    licensed_capacity: int = Field(ge=0)
    source: str


class WindForecast(Model):
    """One wind forecast value (NOAA HRRR), as it was issued. Files may hold many grid points
    per forecast; consumers pick by location."""

    run_at: AwareDatetime | None = Field(None, description="The model run (cycle) time")
    issued_at: AwareDatetime | None = Field(
        None,
        description="When this forecast became available, ONLY if the source records it. Leave "
        "empty and run_at + the assumed publish delay (backend/assumptions.py) is used.",
    )
    valid_at: AwareDatetime = Field(description="The time the forecast is for")
    lat: float
    lon: float
    speed_ms: float = Field(ge=0, description="10 m wind speed, metres per second")
    dir_from_deg: float = Field(
        ge=0, lt=360, description="Direction the wind blows FROM, degrees clockwise from true north"
    )
    gust_ms: float | None = None

    @model_validator(mode="after")
    def _has_time(self) -> WindForecast:
        if self.issued_at is None and self.run_at is None:
            raise ValueError("give run_at (the model run time) or issued_at")
        return self

    def visible_from(self) -> datetime | None:
        if self.issued_at is not None:
            return self.issued_at
        return self.run_at + timedelta(minutes=HRRR_PUBLISH_LAG_MIN)


class EvacOrder(Model):
    """A real evacuation warning or order, hand-mapped from after-action reviews."""

    zone_id: str
    kind: Literal["warning", "order"]
    issued_at: AwareDatetime
    area: str = Field(description="Human-readable area name")
    polygon: list[list[float]] | None = Field(
        None, description="Zone outline as [lon, lat] pairs (GeoJSON order)"
    )
    source: str = Field(description="Where this time came from (URL or citation)")

    def visible_from(self) -> datetime | None:
        return self.issued_at


class Shelter(Model):
    """A drop-off point. Real shelters opened during the night, so each has an opening time."""

    id: str
    name: str
    lat: float
    lon: float
    capacity: int | None = None
    opened_at: AwareDatetime | None = Field(
        None, description="When it opened for evacuees. None = open before the fire")
    source: str | None = Field(None, description="Citation for the location and opening time")

    def visible_from(self) -> datetime | None:
        return self.opened_at


class HelpRequest(Model):
    """A structured help request. The Intake agent turns free text into this; the backend
    fills in every number (coordinates, cell, vehicle types, load time)."""

    address: str | None = Field(
        None, description="Street address with house number and city, as the caller said it. "
        "The backend looks up the coordinates.", examples=["2260 N Lake Ave, Altadena, CA"])
    needs: Need = Field(description="wheelchair, oxygen, bedbound, no_car (can move but has no "
                        "ride), or none")
    people: int = Field(1, ge=1, description="How many people need the ride")
    notes: str | None = Field(None, examples=["on oxygen, 2nd floor"])
    raw_text: str | None = Field(None, description="Original message, kept for audit")
    reported_at: AwareDatetime | None = Field(
        None, description="When the call came in. Omit to use the replay clock's current time.")
    lat: float | None = Field(None, description="Only if known from a device, never estimated")
    lon: float | None = Field(None, description="Only if known from a device, never estimated")

    @model_validator(mode="after")
    def _has_location(self) -> HelpRequest:
        if not self.address and (self.lat is None or self.lon is None):
            raise ValueError("give an address (house number, street, city) or lat and lon")
        return self


class ResidentRisk(Model):
    """Risk engine output for one resident at time t."""

    resident_id: str
    t: AwareDatetime
    p_1h: float = Field(ge=0, le=1)
    p_2h: float = Field(ge=0, le=1)
    p_3h: float = Field(ge=0, le=1)
    arrival_p10_min: float | None = None
    deadline_min: float | None = Field(
        None, description="Pick up within this many minutes after t. None = no deadline in horizon"
    )
    priority: float = Field(ge=0, description="Higher = more urgent")
    at_risk: bool = Field(description="True = the router must route or escalate this person")


class WorldState(Model):
    """Everything the dashboard needs at time t, in one message."""

    t: AwareDatetime
    dataset: str
    residents: list[Resident]
    vehicles: list[Vehicle]
    shelters: list[Shelter]
    detections: list[FireDetection]
    reports: list[FireReport]
    facilities: list[Facility]
    orders: list[EvacOrder]
    outlook: list[FireOutlook]
    risks: list[ResidentRisk]
    plan: Plan
    decisions: list[Decision]
    # Replay state, so the dashboard can show vehicles actually moving.
    picked_up: dict[str, AwareDatetime] = Field(
        default_factory=dict, description="Resident id -> when a vehicle left with them"
    )
    schedule: list[Route] = Field(
        default_factory=list,
        description="What each vehicle is actually doing: remaining approved stops, ETAs in "
        "minutes after t",
    )
    plan_takes_effect_at: AwareDatetime | None = Field(
        None, description="When the plan above is approved and vehicles start following it"
    )


def capacity_demand(resident: Resident) -> tuple[int, int, int]:
    """(seats, wheelchair spaces, stretcher spaces) this resident's party uses in a vehicle.

    A wheelchair user takes a wheelchair space and a bedbound person a stretcher; everyone
    else in the party takes a seat.
    """
    if resident.needs == "wheelchair":
        return resident.people - 1, 1, 0
    if resident.needs == "bedbound":
        return resident.people - 1, 0, 1
    return resident.people, 0, 0
