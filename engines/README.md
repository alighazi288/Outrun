# Engines

Engines compute every number in Outrun. Agents never do math: they call these through the API
and explain the results. Each engine is a **pure function**: same inputs, same outputs, no hidden
state, no network calls. That makes them easy to test, replay and evaluate.

Each engine started simple and deterministic so the API, dashboard and agents worked end to end.
Any engine can be replaced behind the **same signature**, and it must pass `tests/test_engines.py`.
Every assumed number goes in `backend/assumptions.py`, not in the engine.

| File | Signature | What it does now | Next (not built) |
|---|---|---|---|
| `nowcast.py` | `nowcast(detections, wind, cells, t, reports)` → `list[FireOutlook]` | A simple spread model: fire spreads fastest downwind from the recent sightings (satellites **and** reports), with log-normal uncertainty. Scored on Eaton and Palisades with `make forecast-check`. It warns hours early but too broadly | Many simulated runs with varied wind and downwind embers. A first try (latest-scan front + fixed ember reach) passed on Palisades, failed on Eaton, and was not kept |
| `risk.py` | `prioritize(residents, outlook, t)` → `list[ResidentRisk]` | deadline = p10 arrival − margin (latest time to *leave*); priority = 3-hour fire chance × need weight | Rank by the chance fire arrives before our earliest possible pickup |
| `travel.py` | `TravelTime.minutes(a, b)`, `cells(a, b)` | Real roads where an area has a road file (`RoadTravel`: OpenStreetMap driving times at `SPEED_FACTOR`, and the cells each route passes). Otherwise a straight-line estimate × 1.3 at 30 km/h (areas set up on demand, test fixtures) | Road files for areas set up on demand; detours around burning or blocked roads |
| `routing.py` | `plan_routes(risks, residents, vehicles, shelters, outlook, travel, t, previous_plan)` → `Plan` | Most urgent first (earliest deadline; ties: priority), within the safety rule. `plan_routes_closest` is the weaker baseline | Nothing planned: an OR-Tools optimizer was tried Oct 12 and was no better on the real night, at 30x the time per step |
| `routing.py` | `plan_routes_dispatcher(...)`, same signature | The bar: most urgent first (earliest deadline), nearest suitable vehicle. Ranking in `evaluation/heuristic.py` | |

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

**Inputs:** satellite detections (VIIRS, GOES), published fire reports, and HRRR wind as issued.
On the Eaton night VIIRS saw nothing until 1:30 a.m., so reports and GOES carry the early hours.

**Next, if there is time** (fit only on Palisades or published values, never on Eaton, EVAL_SPEC §8):
1. Many runs per step with wind drawn around the forecast, **plus ember spotting downwind** as a
   chance, not a certainty (spot fires start some of the time and take time to grow).
2. p_1h = the share of runs where fire reached the cell within 1 h; arrival_p10_min = the 10th
   percentile of arrival time across runs.
3. Score on Palisades with `make forecast-check` (watch the share of the map closed to drivers),
   then run Eaton once.

## Roads and driver safety

Altadena's road times come from OpenStreetMap (`scripts/build_roads.py`, `uv sync --extra
routing`): the shortest path between every pair of map cells at `SPEED_FACTOR` × road speed, and
the cells each route passes, so the safety rule checks the real road. Areas set up on demand
use the straight-line estimate until they get a road file.

**Risk.** It ignores travel time, so the most urgent person can be one nobody can reach in
time; the planner then lists them for fire command. Ranking by the chance fire arrives before
our earliest possible pickup would fix that.
