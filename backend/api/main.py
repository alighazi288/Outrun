"""Outrun backend API.

REST endpoints for the dashboard and for watsonx Orchestrate agents (imported as OpenAPI
tools; the `operation_id` of each endpoint becomes the tool name), plus a WebSocket that
pushes the world state every time the replay clock steps.

Run it:  uv run outrun-api        Docs:  http://localhost:8000/docs
Tests build their own app with create_app(store=...), so nothing runs at import time.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3
import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AwareDatetime, BaseModel, Field

from backend.assumptions import HANDLING_DELAY_MIN
from backend.clock import parse_t
from backend.decision_log import DecisionLog
from backend.geocode import census_geocode
from backend.schemas import (
    H3_RES,
    NEED_PROFILES,
    Decision,
    FireOutlook,
    FireReport,
    HelpRequest,
    Plan,
    Resident,
    WorldState,
)
from backend.sim import Simulation
from backend.store import REPO_ROOT, DataStore
from engines.nowcast import wind_at

Geocoder = Callable[[str], "tuple[float, float] | None"]

T_QUERY = Query(
    None,
    description="Replay time, ISO-8601 with offset, e.g. 2025-01-07T23:40:00-08:00. "
    "Omit to use the replay clock's current time.",
)


class ClockInfo(BaseModel):
    start: AwareDatetime
    end: AwareDatetime
    step_minutes: int
    now: AwareDatetime


class OutlookSummary(BaseModel):
    t: AwareDatetime
    wind_speed_ms: float
    wind_from_deg: float
    cells_burning: int
    cells_p1h_over_50: int
    cells_p3h_over_50: int
    top_cells: list[FireOutlook]


class FireReportIn(BaseModel):
    """A fire sighting, structured by the Intake agent from a call or radio message."""

    address: str | None = Field(
        None, description="Nearest street address with house number and city. The backend "
        "looks up the coordinates.", examples=["2260 N Lake Ave, Altadena, CA"])
    description: str = Field(description="What was seen, in a short sentence")
    raw_text: str | None = None
    reported_at: AwareDatetime | None = Field(
        None, description="When it was reported. Omit to use the replay clock's current time.")
    lat: float | None = Field(None, description="Only if known from a device, never estimated")
    lon: float | None = Field(None, description="Only if known from a device, never estimated")
    location_precision_m: float = Field(250.0, ge=0)


class AtRiskEntry(BaseModel):
    id: str
    needs: str
    people: int
    lat: float
    lon: float
    source: str
    p_1h: float
    p_3h: float
    arrival_p10_min: float | None
    deadline_min: float | None
    priority: float


class VehicleRun(BaseModel):
    """What one vehicle is doing at time t."""

    vehicle: str
    type: str
    status: str
    free_in_min: float = Field(description="Minutes until it finishes its current run")
    stops: list[str] = Field(description="Remaining stops in order: resident ids, then a shelter")
    eta_min: list[float] = Field(description="Minutes after t until each stop")


def create_app(store: DataStore | None = None, log_path: Path | None = None,
               geocode: Geocoder = census_geocode) -> FastAPI:
    store = store or DataStore.from_env()
    sim = Simulation(store)
    clock = store.make_clock()
    log = DecisionLog(log_path)
    logged_plans: set[str] = set()
    sockets: set[WebSocket] = set()

    # The address Orchestrate calls (it's written into the OpenAPI spec). Render sets
    # RENDER_EXTERNAL_URL itself; OUTRUN_PUBLIC_URL overrides it (e.g. for a tunnel).
    public_url = (os.environ.get("OUTRUN_PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL")
                  or "http://localhost:8000")
    app = FastAPI(
        title="Outrun API",
        version="0.1.0",
        description=(
            "Wildfire evacuation dispatch for residents who can't evacuate alone. "
            "Every number comes from an engine; agents call these tools and explain results."
        ),
        servers=[{"url": public_url}],
    )
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])

    def at(t: datetime | None) -> datetime:
        if t is None:
            return clock.now
        if t.tzinfo is None:
            raise HTTPException(422, "t must include a UTC offset, e.g. -08:00")
        return t

    async def locate(lat: float | None, lon: float | None,
                     address: str | None) -> tuple[float, float]:
        """Coordinates from the caller's address (or a device), inside the area we cover.
        The error messages are written for the agent to act on."""
        if lat is not None and lon is not None:
            point = (lat, lon)
        elif address:
            try:
                point = await asyncio.to_thread(geocode, address)  # don't block other calls
            except OSError as e:
                raise HTTPException(503, "Address lookup is unavailable right now. Try again "
                                    "in a minute.") from e
            if point is None:
                raise HTTPException(422, f"Address not found: '{address}'. Ask the caller for "
                                    "the house number, street and city, or the nearest address.")
        else:
            raise HTTPException(422, "No location. Ask the caller for their address.")
        box = store.meta["bbox"]
        inside = box["south"] <= point[0] <= box["north"] and box["west"] <= point[1] <= box["east"]
        if not inside:
            raise HTTPException(422, "That address is outside the area Outrun covers, so it "
                                "can't be added to this plan.")
        return point

    def state(t: datetime) -> WorldState:
        return sim.world_state(t, log.decisions_at(t))

    async def broadcast() -> None:
        payload = state(clock.now).model_dump_json()
        for ws in list(sockets):
            try:
                await ws.send_text(payload)
            except Exception:
                sockets.discard(ws)

    def clock_info() -> ClockInfo:
        return ClockInfo(start=clock.start, end=clock.end, now=clock.now,
                         step_minutes=int(clock.step.total_seconds() // 60))

    @app.get("/health", operation_id="health")
    def health() -> dict:
        return {"status": "ok", "dataset": store.name, "now": clock.now.isoformat()}

    @app.get("/clock", operation_id="get_clock", summary="Current replay time")
    def get_clock() -> ClockInfo:
        return clock_info()

    @app.post("/clock/step", operation_id="step_clock", summary="Advance the replay clock")
    async def step_clock(n: int = Query(1, ge=1, le=100)) -> ClockInfo:
        clock.advance(n)
        await broadcast()
        return clock_info()

    @app.post("/clock/reset", operation_id="reset_clock", summary="Rewind to the start")
    async def reset_clock() -> ClockInfo:
        clock.reset()
        await broadcast()
        return clock_info()

    @app.get("/state", operation_id="get_world_state",
             summary="Everything the dashboard shows at time t")
    def get_state(t: datetime | None = T_QUERY) -> WorldState:
        return state(at(t))

    @app.get(
        "/fire/outlook",
        operation_id="get_fire_outlook",
        summary="Where the fire is likely to be in the next 1, 2 and 3 hours",
        description="Summary counts plus the most threatened map cells. Use it to describe "
        "the fire situation. All probabilities come from the nowcast engine.",
    )
    def get_fire_outlook(t: datetime | None = T_QUERY,
                         limit: int = Query(25, ge=1, le=500)) -> OutlookSummary:
        t = at(t)
        step = sim.step(t)
        speed, dir_to = wind_at(step.snapshot.wind, t)
        cells = step.outlook
        return OutlookSummary(
            t=t,
            wind_speed_ms=round(speed, 1),
            wind_from_deg=round((dir_to + 180) % 360, 1),
            cells_burning=sum(c.burning for c in cells),
            cells_p1h_over_50=sum(c.p_1h > 0.5 for c in cells),
            cells_p3h_over_50=sum(c.p_3h > 0.5 for c in cells),
            top_cells=sorted((c for c in cells if not c.burning),
                             key=lambda c: -c.p_1h)[:limit],
        )

    @app.get(
        "/residents/at-risk",
        operation_id="get_residents_at_risk",
        summary="Residents who need help, most urgent first",
        description="Each entry has the fire probability at their home, the pessimistic fire "
        "arrival, their rescue deadline and priority score, all computed by engines.",
    )
    def get_residents_at_risk(t: datetime | None = T_QUERY,
                              limit: int = Query(20, ge=1, le=500)) -> list[AtRiskEntry]:
        step = sim.step(at(t))
        res = {r.id: r for r in step.snapshot.residents}
        return [
            AtRiskEntry(id=k.resident_id, needs=res[k.resident_id].needs,
                        people=res[k.resident_id].people, lat=res[k.resident_id].lat,
                        lon=res[k.resident_id].lon, source=res[k.resident_id].source,
                        p_1h=k.p_1h, p_3h=k.p_3h, arrival_p10_min=k.arrival_p10_min,
                        deadline_min=k.deadline_min, priority=k.priority)
            for k in step.risks if k.at_risk
        ][:limit]

    @app.get(
        "/plan",
        operation_id="get_current_plan",
        summary="The proposed rescue plan at time t",
        description="New assignments waiting for approval (routes per vehicle with ETAs), people "
        "no vehicle can reach in time (unreachable, must be escalated) and a reason per person. "
        "Vehicles keep the run they are already on; see get_vehicle_runs for those.",
    )
    def get_plan(t: datetime | None = T_QUERY) -> Plan:
        plan = sim.step(at(t)).plan
        if plan.plan_id not in logged_plans:
            logged_plans.add(plan.plan_id)
            log.record("plan", plan)
        return plan

    @app.get(
        "/vehicles",
        operation_id="get_vehicle_runs",
        summary="What each vehicle is doing now",
        description="Every vehicle with its status and the run it is already driving: remaining "
        "stops in order (resident ids, then a shelter) with ETAs in minutes after t. These runs "
        "are approved and in progress; get_current_plan only holds new assignments.",
    )
    def get_vehicle_runs(t: datetime | None = T_QUERY) -> list[VehicleRun]:
        frame = sim.step(at(t))
        runs = {r.vehicle: r for r in frame.schedule}
        return [
            VehicleRun(vehicle=v.id, type=v.type, status=v.status,
                       free_in_min=v.available_in_min,
                       stops=runs[v.id].stops if v.id in runs else [],
                       eta_min=runs[v.id].eta_min if v.id in runs else [])
            for v in frame.vehicles
        ]

    @app.post(
        "/requests",
        operation_id="submit_help_request",
        status_code=201,
        summary="Add a help request to the plan",
        description="Send a structured request: the caller's address, needs, people, notes. "
        "The backend looks up the coordinates and fills in the map cell, vehicle types and "
        "loading time. If the address isn't found, the error says what to ask the caller. The "
        "person becomes visible to the planner after the call-handling delay.",
    )
    async def submit_help_request(req: HelpRequest) -> Resident:
        lat, lon = await locate(req.lat, req.lon, req.address)
        req = req.model_copy(update={"lat": lat, "lon": lon,
                                     "reported_at": req.reported_at or clock.now})
        vehicle_types, load_minutes = NEED_PROFILES[req.needs]
        n = sum(r.source == "request" for r in store.residents) + 1
        resident = Resident(
            id=f"q_{n:04d}", lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES),
            needs=req.needs, vehicle_types=vehicle_types, load_minutes=load_minutes,
            people=req.people, source="request",
            known_at=req.reported_at + timedelta(minutes=HANDLING_DELAY_MIN),
            notes=req.notes,
        )
        store.add_resident(resident)
        sim.invalidate()
        logged_plans.clear()
        log.record("request", req)
        await broadcast()
        return resident

    @app.post(
        "/reports",
        operation_id="submit_fire_report",
        status_code=201,
        summary="Add a report of fire at a place and time",
        description="Send a structured fire sighting: the nearest address, what was seen. The "
        "backend looks up the coordinates. It feeds the fire forecast from reported_at onward, "
        "alongside satellite detections.",
    )
    async def submit_fire_report(req: FireReportIn) -> FireReport:
        lat, lon = await locate(req.lat, req.lon, req.address)
        req = req.model_copy(update={"lat": lat, "lon": lon,
                                     "reported_at": req.reported_at or clock.now})
        n = sum(r.source == "intake" for r in store.reports) + 1
        report = FireReport(
            id=f"fr_intake_{n:04d}", lat=lat, lon=lon, h3=h3.latlng_to_cell(lat, lon, H3_RES),
            reported_at=req.reported_at, description=req.description,
            location_precision_m=req.location_precision_m, source="intake",
        )
        store.add_report(report)
        sim.invalidate()
        logged_plans.clear()
        log.record("report", req)
        await broadcast()
        return report

    @app.post(
        "/decisions",
        operation_id="record_decision",
        status_code=201,
        summary="Record what the emergency manager did with a plan",
        description="Call only after the emergency manager explicitly says approve, modify or "
        "reject, with the plan_id from get_current_plan. Never approve on your own.",
    )
    async def record_decision(d: Decision) -> Decision:
        log.record("decision", d)
        await broadcast()
        return d

    @app.get("/decisions", operation_id="list_decisions", summary="All recorded decisions",
             description="Every approve, modify or reject decision recorded so far, in order.")
    def list_decisions() -> list[Decision]:
        return log.decisions

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        """Sends WorldState on connect and after every clock step, request or decision.
        Send {"t": "<iso time>"} to get the state at another time."""
        await websocket.accept()
        sockets.add(websocket)
        try:
            await websocket.send_text(state(clock.now).model_dump_json())
            while True:
                msg = await websocket.receive_json()
                if "t" in msg:
                    t = parse_t(msg["t"])
                    await websocket.send_text(state(t).model_dump_json())
        except WebSocketDisconnect:
            sockets.discard(websocket)

    return app


def _default_log_path() -> Path:
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return REPO_ROOT / "data" / "runs" / run_id / "log.jsonl"


def default_app() -> FastAPI:
    """App factory used by `outrun-api` (and `uvicorn --factory backend.api.main:default_app`)."""
    return create_app(log_path=_default_log_path())


def run() -> None:
    uvicorn.run("backend.api.main:default_app", factory=True, host="0.0.0.0",
                port=int(os.environ.get("PORT", 8000)))
