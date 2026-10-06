# Engines

Engines compute every number in Outrun. Agents never do math: they call these through the API
and explain the results. Each engine is a **pure function**: same inputs, same outputs, no hidden
state, no network calls. That makes them easy to test, replay and evaluate.

Each engine will ship as a **stub**: simple, plausible and deterministic, so the API, dashboard
and agents work end to end. We can then replace the stub behind the **same signature**, and it must pass
`tests/test_engines.py`. Every assumed number goes in `backend/assumptions.py`, not in the engine.

| File | Signature | Stub | Real version |
|---|---|---|---|
| `nowcast.py` | `nowcast(detections, wind, cells, t, reports)` → `list[FireOutlook]` | elliptical spread from recent fire evidence (detections **and** reports) + log-normal uncertainty | spread fitted from past fires; 100+ Monte Carlo runs with varied wind; **downwind embers** |
| `risk.py` | `prioritize(residents, outlook, t)` → `list[ResidentRisk]` | deadline = p10 arrival − margin (latest time to *leave*); priority = p_3h × weight | P(fire arrives before our earliest pickup) × weight |
| `travel.py` | `TravelTime.minutes(a, b)` | straight line × 1.3 at 30 km/h | OSMnx shortest path at `SPEED_FACTOR` × road speed, blocked roads removed; reports the hexes on the path |
| `routing.py` | `plan_routes(risks, residents, vehicles, shelters, outlook, travel, t, previous_plan)` → `Plan` | closest first, within the safety rule | OR-Tools pickup-and-delivery + rolling re-plan |
| `routing.py` | `plan_routes_dispatcher(...)`, same signature | most urgent first (earliest deadline), nearest suitable vehicle | this is the bar; the ranking is in `evaluation/heuristic.py` |

## Rules for every implementation
1. **Never drop anyone silently.** Every at-risk resident ends up in a route or in `unreachable`.
   Those too late or only reachable through danger are also listed in `escalated_fire_command`.
2. **Driver safety.** For every hex a vehicle occupies (stops and the hexes between them):
   leave time + `SAFETY_MARGIN_MIN` ≤ that hex's `arrival_p10_min`. Burning hexes are never entered.
   No pickup without a safe way out to a shelter. Use `SafetyMap` from `routing.py`.
3. **Reasons come from numbers.** Build them with f-strings from your outputs.
4. **Assumed numbers live in `assumptions.py`** with a status and a tested range.
5. **Keep it fast.** One step well under a second; the evaluation runs ~2,200 full replays.

## Fire nowcast 

**Inputs:** satellite detections, published fire reports, and wind. On the real night, VIIRS saw
nothing until 1:30 a.m., so reports carry the early hours.

Real version, in order:
1. Download VIIRS (FIRMS) and **GOES** detections for Jan 7–8 around Altadena. **FIRST THING TO ANSWER:
   what did satellites see over west Altadena between 22:00 and 03:25?** That decides how much the
   forecast leans on reports.
2. Pull HRRR wind as issued, with `herbie` (`uv sync --extra wx`). Use `issued_at` = when the run
   was available.
3. Fit spread rates from past fires or published values, never from Eaton outcomes (EVAL_SPEC §8).
4. Monte Carlo: 100+ runs per step with wind drawn around the forecast, **plus ember spotting
   downwind**. That's the ahead-of-the-front danger the investigations describe.
   - p_1h = the share of runs where fire reached the cell within 1 h
   - arrival_p10_min = the 10th percentile of arrival time across runs
5. Score it: Brier and calibration against DINS + timelines (EVAL_SPEC §8).

## Roads, routing, driver safety

**Travel time.** Build the Altadena drive network with OSMnx (`uv sync --extra routing`). Implement
`TravelTime.minutes(a, b)` as a shortest path at `SPEED_FACTOR` × road speed, with blocked roads
removed, cached per step. Also expose the hexes along the path, so the safety rule checks real
roads instead of straight lines.

**OR-Tools router** (pickup and delivery with time windows):
- **Nodes:** vehicle starts, each at-risk person, and shelters (repeated so vehicles can do several trips).
- **Capacities:** seats, wheelchair spaces and stretchers (`capacity_demand()`).
- **Time dimension:** travel + `load_minutes`. A pickup's *departure* must be ≤ `deadline_min`.
- **Pairs:** each person is picked up and dropped at a shelter by the same vehicle.
- **Vehicle types:** restrict each person to the vehicle types in `vehicle_types`.
- **Skipping:** may skip a person at a penalty proportional to `priority`. Skipped people go to `unreachable`.
- **Safety:** forbid arcs through unsafe hexes (`SafetyMap`).
- **Re-planning:** use `previous_plan` to keep vehicles on their current run unless switching saves a lot.

Add it to `ROUTERS` in `tests/test_engines.py`. It must pass every test, including
`test_router_driver_safety`.

**Risk.** The stub is naturally going to ignore travel time, so the most urgent person can be one nobody can reach. The real version should rank by the chance fire arrives **before our earliest possible pickup**.
