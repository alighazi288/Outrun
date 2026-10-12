"""Build data/processed/eaton/roads.json.gz: road travel times between map cells, and their routes.

From the OpenStreetMap drive network (via OSMnx), covering the study area plus the shelters and
the vehicle yard. For every pair of "places" (each study-area cell, and the cells holding a
shelter or a depot) it stores:
- the free-flow driving minutes between them (OSM speed limits, or OSMnx's typical speed for
  the road type where none is posted); the planner slows this down by SPEED_FACTOR at run time,
- the next place on that route, so the route's cells can be walked: the driver-safety rule then
  checks the cells the road really passes through, not a straight line.
Each place starts from the road node nearest its centre; the short hop to it is added at the
straight-line stub speed. The engine reading this file needs no extra packages
(engines/travel.py RoadTravel).

Known limits: roads are today's OSM, not a Jan 2025 snapshot (Altadena's streets did not
change); routes are fixed per pair, so a burning cell on the fastest route blocks the trip
rather than causing a detour.

    uv sync --group dev --extra routing
    uv run python scripts/build_roads.py
"""

from __future__ import annotations

import base64
import gzip
import json
import math
import sys
from array import array
from datetime import UTC, datetime

import h3
import networkx as nx
import numpy as np
import osmnx as ox

from backend.assumptions import STUB_SPEED_KMH
from backend.schemas import H3_RES, Shelter, Vehicle
from backend.store import DATA_DIR, DATASETS, grid_cells, read_jsonl
from engines.travel import ROAD_UNREACHABLE, haversine_m

RAW = DATA_DIR / "raw" / "roads" / "eaton_drive.graphml"
ox.settings.cache_folder = str(DATA_DIR / "raw" / "osmnx_cache")  # not ./cache in the repo
MARGIN_DEG = 0.01  # ~1 km of road beyond the outermost place


def places() -> tuple[list[str], dict]:
    """Study-area cells first, then the cells holding a shelter or depot outside it."""
    folder = DATASETS["eaton"]
    bbox = json.loads((folder / "meta.json").read_text())["bbox"]
    cells = list(grid_cells(bbox))
    points = [(s.lat, s.lon) for s in read_jsonl(folder / "shelters.jsonl", Shelter)]
    points += [(v.lat, v.lon) for v in read_jsonl(folder / "vehicles.jsonl", Vehicle)]
    for lat, lon in points:
        c = h3.latlng_to_cell(lat, lon, H3_RES)
        if c not in cells:
            cells.append(c)
    lats = [h3.cell_to_latlng(c)[0] for c in cells]
    lons = [h3.cell_to_latlng(c)[1] for c in cells]
    box = {"west": min(lons) - MARGIN_DEG, "south": min(lats) - MARGIN_DEG,
           "east": max(lons) + MARGIN_DEG, "north": max(lats) + MARGIN_DEG}
    return cells, box


def road_graph(box: dict) -> nx.MultiDiGraph:
    if not RAW.exists():
        RAW.parent.mkdir(parents=True, exist_ok=True)
        g = ox.graph_from_bbox((box["west"], box["south"], box["east"], box["north"]),
                               network_type="drive")
        ox.save_graphml(g, RAW)
    g = ox.load_graphml(RAW)
    g = ox.routing.add_edge_speeds(g)
    return ox.routing.add_edge_travel_times(g)


def build() -> dict:
    cells, box = places()
    g = road_graph(box)
    index = {c: i for i, c in enumerate(cells)}
    nodes = list(g.nodes)
    ys = np.array([g.nodes[n]["y"] for n in nodes])
    xs = np.array([g.nodes[n]["x"] for n in nodes])
    node_cell = {n: h3.latlng_to_cell(y, x, H3_RES) for n, y, x in zip(nodes, ys, xs, strict=True)}

    # Each place starts at the road node nearest its centre (flat-earth distance is fine here).
    start, access = [], []
    for c in cells:
        lat, lon = h3.cell_to_latlng(c)
        d2 = (ys - lat) ** 2 + ((xs - lon) * math.cos(math.radians(lat))) ** 2
        k = int(d2.argmin())
        start.append(nodes[k])
        access.append(haversine_m((lat, lon), (ys[k], xs[k])) / 1000 / STUB_SPEED_KMH * 60)

    n = len(cells)
    minutes = array("f", [ROAD_UNREACHABLE]) * (n * n)
    nxt = array("H", [0]) * (n * n)
    reverse = g.reverse(copy=False)
    for j, dst in enumerate(start):
        # Shortest paths TO this place: every route below heads to the same destination, and
        # each next hop is strictly closer to it, so walking the hops can never loop.
        to_dst, back = nx.single_source_dijkstra(reverse, dst, weight="travel_time")
        for i, src in enumerate(start):
            k = i * n + j
            if i == j or src not in to_dst:
                minutes[k] = 0.0 if i == j else ROAD_UNREACHABLE
                nxt[k] = j
                continue
            minutes[k] = to_dst[src] / 60 + access[i] + access[j]
            hop = j
            for node in reversed(back[src]):  # the road from this place to the destination
                c = node_cell[node]
                h = index.get(c)
                if h is not None and h != i and to_dst.get(start[h], math.inf) < to_dst[src]:
                    hop = h
                    break
            nxt[k] = hop
        if j % 100 == 0:
            print(f"  routes to {j}/{n} places", file=sys.stderr)
    if sys.byteorder == "big":
        minutes.byteswap()
        nxt.byteswap()
    return {
        "source": "OpenStreetMap contributors (ODbL), drive network via OSMnx; free-flow minutes",
        "built": datetime.now(UTC).date().isoformat(),
        "cells": cells,
        "minutes_f32_le": base64.b64encode(minutes.tobytes()).decode(),
        "next_u16_le": base64.b64encode(nxt.tobytes()).decode(),
        "graph": {"nodes": g.number_of_nodes(), "edges": g.number_of_edges()},
    }


def main() -> None:
    data = build()
    out = DATASETS["eaton"] / "roads.json.gz"
    with gzip.open(out, "wt") as f:
        json.dump(data, f)
    print(f"Wrote road times for {len(data['cells'])} places "
          f"({data['graph']['nodes']} road nodes) -> {out}")


if __name__ == "__main__":
    main()
