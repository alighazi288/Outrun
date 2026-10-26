"""The live server: Outrun for any US area, on today's data.

    uv run outrun-live            # http://localhost:8001/docs   (or: make live)

    GET  /fires                  real US wildfires: new in the last few days or not contained
    GET  /areas                  the areas set up so far
    POST /areas                  set one up (a fire from /fires, or any point): ~10-20 s
    /areas/<name>/...            that area's own Outrun API: the same endpoints the dashboard,
                                 the manager and the agents use for the Eaton replay
                                 (/state, /plan, /decisions, /reports, /ws ...), plus /drill

Each area runs on the real clock and pulls its feeds again when they are 10 minutes old
(backend/api/main.py). Areas live in data/live/ and are mounted again when the server starts.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from backend import area
from backend.api.main import create_app
from backend.store import DataStore


class AreaIn(BaseModel):
    """Where to set up: a fire from GET /fires (fire_id), or any point with a name."""

    fire_id: str | None = Field(None, description="An id from GET /fires")
    lat: float | None = None
    lon: float | None = None
    name: str | None = Field(None, description="Short name, e.g. 'paradise-ca'")


class AreaOut(BaseModel):
    name: str
    url: str = Field(description="This area's Outrun API, relative to the live server")
    description: str
    center: list[float]
    set_up_at: str
    feeds_pulled_at: str | None = None
    fire_weather: list[str] = []
    incident: dict | None = None
    approximations: list[str] = []


def create_live_app(root: Path = area.AREA_ROOT,
                    fires: Callable[[int], list[dict]] = lambda days: area.us_fires(days),
                    setup: Callable[..., Path] = area.setup) -> FastAPI:
    app = FastAPI(title="Outrun live", version="0.1.0",
                  description="Outrun for any US area, on today's fire, wind and alerts.")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
                       allow_headers=["*"])
    areas: dict[str, DataStore] = {}

    def mount(folder: Path) -> DataStore:
        store = DataStore(folder)
        app.mount(f"/areas/{folder.name}",
                  create_app(store=store, log_path=folder / "log.jsonl"))
        areas[folder.name] = store
        return store

    def describe(name: str) -> AreaOut:
        meta = areas[name].meta
        return AreaOut(name=name, url=f"/areas/{name}", description=meta["description"],
                       center=meta["center"], set_up_at=meta["set_up_at"],
                       feeds_pulled_at=meta.get("feeds_pulled_at"),
                       fire_weather=meta.get("fire_weather", []),
                       incident=meta.get("incident"),
                       approximations=meta.get("approximations", []))

    if root.exists():
        for folder in sorted(root.iterdir()):
            meta = folder / "meta.json"
            if not meta.exists():
                continue
            info = json.loads(meta.read_text())
            if info.get("live") and "feeds_pulled_at" in info:  # skip a half-built area
                mount(folder)

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse("/docs")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "areas": sorted(areas)}

    @app.get("/fires", summary="Real US wildfires: new in the last few days, or not contained")
    async def list_fires(days: int = Query(3, ge=1, le=14)) -> list[dict]:
        return await asyncio.to_thread(fires, days)

    @app.get("/areas", summary="The areas set up so far")
    def list_areas() -> list[AreaOut]:
        return [describe(n) for n in sorted(areas)]

    @app.post("/areas", status_code=201, summary="Set up an area (usually 10-20 seconds)")
    async def add_area(req: AreaIn) -> AreaOut:
        fire = None
        if req.fire_id:
            fire = next((f for f in await asyncio.to_thread(fires, 14)
                         if f["id"] == req.fire_id), None)
            if fire is None:
                raise HTTPException(404, f"No current fire with id {req.fire_id}")
            lat, lon = fire["lat"], fire["lon"]
            name = req.name or f"{fire['name']} {fire['place']}"
        elif req.lat is not None and req.lon is not None and req.name:
            lat, lon, name = req.lat, req.lon, req.name
        else:
            raise HTTPException(422, "Give fire_id, or lat, lon and name")
        slug = area.slug(name)
        if slug in areas:
            return describe(slug)
        try:
            folder = await asyncio.to_thread(setup, lat, lon, name, fire=fire)
        except Exception as e:  # a public data service is down or refusing us right now
            shutil.rmtree(root / slug, ignore_errors=True)
            raise HTTPException(503, f"{e}. A public data service may be busy: try again "
                                "in a minute.") from e
        mount(folder)
        return describe(folder.name)

    return app


def default_app() -> FastAPI:
    return create_live_app()


def run() -> None:
    uvicorn.run("backend.live:default_app", factory=True, host="0.0.0.0",
                port=int(os.environ.get("PORT", 8001)))
