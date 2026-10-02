# Architecture

Stack is taken from the project brief. Evaluation and safety follow Ali's reply on 2026-09-30, updated 2026-10-01 with the official Eaton investigations (rules and values in `docs/EVAL_SPEC.md`). Items marked **unknown** are not decided yet.

## What is in the repo

Checked against `main` on 2026-10-02, through commit `bdded46`.

The repo has the folder layout, `pyproject.toml`, `uv.lock`, the Makefile, CI, `.env.example`, `DATA_SOURCES.md`, and these docs. Ali committed the structure and `docs/EVAL_SPEC.md` on October 1. Bhavaani committed the first README and the data-source list.

These names are the contract for the cards. The files are not in the repo yet: `backend/schemas.py`, `assumptions.py`, `clock.py`, `knowledge.py`, the API, the engines, the tests, the agent YAML, and the dashboard app. `docs/HOW_IT_WORKS.md`, `docs/TEAM_PLAYBOOK.md`, and `docs/SUBMISSION.md` are linked and also missing. A module counts as built when it is in the repo and `make check` passes.

## Layers

1. **Data.** Public sources only, filtered to "issued, observed, or reported before time t". One county, Eaton. Keep `DATA_SOURCES.md` for attribution.
   - Fire inputs are published fire reports (the investigations' timelines) and satellite detections. The VIIRS satellite's first detection of the fire came at 1:30 a.m., hours after the first reports west of Lake Avenue.
   - Residents are never real people. Care facilities come from public licensing data; everyone else is sampled from Census counts.
2. **Engines.** Fire nowcast, risk and priority, route optimizer. These are the only source of probabilities, deadlines, and routes.
   - The nowcast is an uncertain signal. Deadlines use its pessimistic side.
   - The optimizer obeys the driver-safety rule.
   - Every assumed number lives in `backend/assumptions.py` with its source or "placeholder" and the range we test.
3. **Agents.** Two watsonx Orchestrate agents (ADK YAML in git, IBM Granite). They never emit numbers.
   - **Intake** turns help requests and fire reports into records.
   - **Dispatch** explains the plan and waits for approval.
   - A third agent is a supervisor only if Orchestrate needs one to route between Intake and Dispatch. The Granite model name is confirmed when the instance is registered.
   - Alert text is a fixed English/Spanish template with blanks filled from engine output.
4. **Dashboard.** React, MapLibre, deck.gl, OpenFreeMap. Shows map (fire outlook, fire reports, detections, care facilities, residents, routes), timeline, approval panel, embedded chat, and the triage weights. Receives live state over WebSocket. The judged demo plays precomputed files.
5. **Evaluation.** Same information limits for every strategy. Sweeps one lever at a time, plus two combined scenarios and the fleet-size curve. Reports ranges.

## Folder structure

In use since 2026-10-01. The brief requires `bob_sessions/` and `DATA_SOURCES.md`.

```
backend/          FastAPI, replay clock, OpenAPI tools; shared data formats (schemas.py)
                  and every assumed number (assumptions.py)
agents/           Orchestrate ADK YAML (Intake, Dispatch)
engines/          nowcast, risk, travel time, optimizer
evaluation/       heuristic, sweeps, arrival window
dashboard/        React map
data/             dataset layout (README), what builds each file (BUILD.md), fixtures,
                  raw/ (not committed), processed/
scripts/          fake-data generator, OpenAPI export, data-build scripts
tests/            contract tests: no hindsight, driver safety, never dropped
notebooks/        exploration
docs/
bob_sessions/
DATA_SOURCES.md
```

`backend`, `engines`, and `evaluation` are packages in one Python project (`pyproject.toml`, uv). `make check` runs what CI runs.

## Data model

H3 resolution 9 (about a city block) is the brief's starting grid. Times are ISO strings in Pacific time; times without a time zone are rejected. Fields live in `backend/schemas.py`.

- **Resident.** id, lat, lon, h3, needs (`wheelchair | oxygen | bedbound | no_car | none`), vehicle_types, load_minutes, people, source, known_at, notes, facility_id.
  - `source` is `facility | estimated | registry | call | request`.
  - Care-facility residents are known from the start.
  - Estimated residents are reported at 0, 25, 50, and 100% pre-registered. Each rate is an assumption. 25% is a point on that curve, and it is the hold point when another lever is swept.
  - Everyone else gets a known_at from a help request: the earlier of a real order covering their home or the first published fire report within 2 km, plus up to 60 minutes, plus 15 minutes before the planner sees it. Live demo requests (`POST`) are labeled examples and also wait 15 minutes.
- **Facility.** id, name, kind, lat, lon, h3, licensed_capacity, source.
- **FireReport.** id, lat, lon, h3, reported_at, description, location_precision_m, source (a citation, or `intake`).
- **Vehicle.** id, type, seats, wheelchair_spaces, stretcher_spaces, lat, lon, status (`idle | en_route | loading`), depot.
- **FireOutlook.** t, h3, p_1h, p_2h, p_3h, arrival_p10_min, burning. arrival_p10_min is the pessimistic deadline input.
- **ArrivalWindow.** h3, earliest plausible arrival, latest plausible arrival. Built from Cal Fire DINS, satellite detections, the published report timelines, and the official order timeline. DINS says which buildings burned. It does not say when.
- **Plan.** t, plan_id, routes (vehicle, stops, eta_min), unreachable, escalated_fire_command, reasons, strategy.
  - A route is invalid if, for any hex it occupies, the time the vehicle leaves plus a 30-minute margin passes that hex's arrival_p10_min. The 30 minutes is an assumption; we also test 15 and 45.
  - People who can be reached only through those hexes, or too late, go to `escalated_fire_command` and are not dropped.
- **Decision.** plan_id, action, by, t, changes, reason. The approval delay is an assumption (5 minutes; also 0, 10, 20). The sweep varies it. The live demo still waits for a person.

Fleet size, speeds, loading times, registry fraction, request delays, approval delay, closure rate, and safety margin are published assumptions. Each one is swept, one at a time. Road blockage and congestion are random closures and slower speeds inside that sweep.

## Where state lives

- Replay frames (fire probabilities, routes, decisions, sweep summaries) are files, precomputed on laptops or Colab. Static playback is the primary demo. Record a backup video.
- DuckDB is available for local analytical reads of those frames.
- Live state is only tool calls, a new help request or fire report, a small optimizer rerun, and the approval. That state sits in the FastAPI process and is pushed to the dashboard on a WebSocket.

## API and data paths the MVP needs

- `GET` world state at time t. Resident reads respect known_at. Every other read is filtered to data from before t.
- WebSocket of that state for the dashboard.
- `POST` a help request (structured by the Intake agent from free text), returning a Resident whose known_at is the report time plus the delay.
- `POST` a fire report (structured by the Intake agent), feeding the nowcast from its report time.
- `POST` approve or change a Plan, appending a Decision.
- OpenAPI tools the agents call: current outlook, ranked residents, latest plan, submit help request, submit fire report, record decision.
- Evaluation driver, offline: run each strategy twice per scenario (true fire path, and forecast), score both against ArrivalWindow, then repeat across the sweep.

## Evaluation design

| Piece | Rule |
|---|---|
| Information | Same registry fraction and the same request delays for our planner, the dispatcher heuristic, and any weaker reference |
| Rescue bar | Most urgent first, nearest suitable vehicle, same safety rule |
| Warning time | Compare with the real evacuation-order times, with precision (share of warned places the fire reached) |
| Upper bound | Plan using the true fire path. Label it as an upper bound |
| Realistic | Plan using the forecast only. Label it as the realistic case |
| Score | Both are scored on the arrival window. A pickup counts only if it is earlier than the earliest plausible arrival |
| Sweeps | One lever at a time around a baseline, plus "bad night" and "good night". 30 synthetic populations per setting, paired |
| Output | Median and range. Lead with warning lead time and the four levers: information, warning time, fleet size, routing. Include the fleet-size curve at 25% and 100% registry |
| Forecast | One event. Report calibration and Brier score as a case study |
| Safety | Contract test: the optimizer must reject routes that enter a hex the vehicle cannot clear in time |
| Freeze | All settings and engine parameters freeze October 18, before any run on real data |

## Hosting

**Unknown which live host is available.** Order: IBM Code Engine on the team account, if it is in the catalog; else Render free tier; else a Cloudflare quick tunnel for development only. The judged link does not depend on that host. Frontend playback: GitHub Pages or Cloudflare Pages. Code and video: GitHub and YouTube. Agent YAML stays in git after the IBM account closes.

## Sources

| Input | Source | Used by |
|---|---|---|
| Fire reports | Published investigations (FSRI, McChrystal review, Citygate), hand-extracted | Nowcast and the arrival window |
| Roads | OpenStreetMap via osmnx | Optimizer |
| Fire detections | NASA FIRMS VIIRS 375 m; NOAA GOES if it covers the night | Nowcast and the arrival window |
| Building damage | Cal Fire DINS | Arrival window (which buildings burned) |
| Wind as issued | NOAA HRRR via herbie | Nowcast |
| Care facilities | California Community Care Licensing | Who needs help |
| Age, disability, no-car | Census ACS | Synthetic population |
| Buildings | Microsoft Global Building Footprints | Synthetic population |
| Evacuation order times | After-action reviews and news, hand-mapped | Warning-time comparison |
| Fuel maps | LANDFIRE | Physics model only, out of MVP |
- **FireOutlook.** t, h3, p_1h, p_2h, p_3h, arrival_p10_min, burning. arrival_p10_min is the pessimistic deadline input.
- **ArrivalWindow.** h3, earliest plausible arrival, latest plausible arrival. Built from Cal Fire DINS, satellite detections, the published report timelines, and the official order timeline. DINS says which buildings burned. It does not say when.
- **Plan.** t, plan_id, routes (vehicle, stops, eta_min), unreachable, escalated_fire_command, reasons, strategy.
  - A route is invalid if, for any hex it occupies, the time the vehicle leaves plus a 30-minute margin passes that hex's arrival_p10_min. The 30 minutes is an assumption; we also test 15 and 45.
  - People who can be reached only through those hexes, or too late, go to `escalated_fire_command` and are not dropped.
- **Decision.** plan_id, action, by, t, changes, reason. The approval delay is an assumption (5 minutes; also 0, 10, 20). The sweep varies it. The live demo still waits for a person.

Fleet size, speeds, loading times, registry fraction, request delays, approval delay, closure rate, and safety margin are published assumptions. Each one is swept, one at a time. Road blockage and congestion are random closures and slower speeds inside that sweep.

## Where state lives

- Replay frames (fire probabilities, routes, decisions, sweep summaries) are files, precomputed on laptops or Colab. Static playback is the primary demo. Record a backup video.
- DuckDB is available for local analytical reads of those frames.
- Live state is only tool calls, a new help request or fire report, a small optimizer rerun, and the approval. That state sits in the FastAPI process and is pushed to the dashboard on a WebSocket.

## API and data paths the MVP needs

- `GET` world state at time t. Resident reads respect known_at. Every other read is filtered to data from before t.
- WebSocket of that state for the dashboard.
- `POST` a help request (structured by the Intake agent from free text), returning a Resident whose known_at is the report time plus the delay.
- `POST` a fire report (structured by the Intake agent), feeding the nowcast from its report time.
- `POST` approve or change a Plan, appending a Decision.
- OpenAPI tools the agents call: current outlook, ranked residents, latest plan, submit help request, submit fire report, record decision.
- Evaluation driver, offline: run each strategy twice per scenario (true fire path, and forecast), score both against ArrivalWindow, then repeat across the sweep.

## Evaluation design

| Piece | Rule |
|---|---|
| Information | Same registry fraction and the same request delays for our planner, the dispatcher heuristic, and any weaker reference |
| Rescue bar | Most urgent first, nearest suitable vehicle, same safety rule |
| Warning time | Compare with the real evacuation-order times, with precision (share of warned places the fire reached) |
| Upper bound | Plan using the true fire path. Label it as an upper bound |
| Realistic | Plan using the forecast only. Label it as the realistic case |
| Score | Both are scored on the arrival window. A pickup counts only if it is earlier than the earliest plausible arrival |
| Sweeps | One lever at a time around a baseline, plus "bad night" and "good night". 30 synthetic populations per setting, paired |
| Output | Median and range. Lead with warning lead time and the four levers: information, warning time, fleet size, routing. Include the fleet-size curve at 25% and 100% registry |
| Forecast | One event. Report calibration and Brier score as a case study |
| Safety | Contract test: the optimizer must reject routes that enter a hex the vehicle cannot clear in time |
| Freeze | All settings and engine parameters freeze October 18, before any run on real data |

## Hosting

**Unknown which live host is available.** Order: IBM Code Engine on the team account, if it is in the catalog; else Render free tier; else a Cloudflare quick tunnel for development only. The judged link does not depend on that host. Frontend playback: GitHub Pages or Cloudflare Pages. Code and video: GitHub and YouTube. Agent YAML stays in git after the IBM account closes.

## Sources

| Input | Source | Used by |
|---|---|---|
| Fire reports | Published investigations (FSRI, McChrystal review, Citygate), hand-extracted | Nowcast and the arrival window |
| Roads | OpenStreetMap via osmnx | Optimizer |
| Fire detections | NASA FIRMS VIIRS 375 m; NOAA GOES if it covers the night | Nowcast and the arrival window |
| Building damage | Cal Fire DINS | Arrival window (which buildings burned) |
| Wind as issued | NOAA HRRR via herbie | Nowcast |
| Care facilities | California Community Care Licensing | Who needs help |
| Age, disability, no-car | Census ACS | Synthetic population |
| Buildings | Microsoft Global Building Footprints | Synthetic population |
| Evacuation order times | After-action reviews and news, hand-mapped | Warning-time comparison |
| Fuel maps | LANDFIRE | Physics model only, out of MVP |
