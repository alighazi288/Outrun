# Architecture

Stack is taken from the project brief. Evaluation and safety follow Ali's reply on 2026-09-30. Items marked **unknown** are not decided yet.

## Layers

1. **Data.** Public sources only, filtered to "issued or observed before time t". Residents are synthetic. One county, Eaton. Keep `DATA_SOURCES.md` for attribution.
2. **Engines.** Fire nowcast, risk and priority, route optimizer. These are the only source of probabilities, deadlines, and routes. The nowcast is an uncertain signal. Deadlines use its pessimistic side.
3. **Agents.** Two or three watsonx Orchestrate agents (ADK YAML in git, IBM Granite). They structure help text, call backend tools, and explain. **Unknown** which two or three. They never emit numbers. Alert text is a fixed English/Spanish template with blanks filled from engine output.
4. **Dashboard.** React, MapLibre, deck.gl, OpenFreeMap. Shows map, timeline, approval panel, embedded chat, and the triage weights. Receives live state over WebSocket. The judged demo plays precomputed files.
5. **Evaluation.** Same information limits for every strategy. Sweeps fleet size, speed, loading time, and approval delay. Reports ranges.

## Folder structure

Proposed, not locked. The brief requires `bob_sessions/` and `DATA_SOURCES.md`.

```
backend/          FastAPI, replay clock, OpenAPI tools
agents/           Orchestrate ADK YAML (2–3 agents)
engines/          nowcast, risk, optimizer
data/             Eaton inputs and precomputed replay frames
evaluation/       heuristic, sweeps, arrival window
dashboard/        React map
docs/
bob_sessions/
DATA_SOURCES.md
```

## Data model

H3 resolution 9 (about a city block) is the brief's starting grid. Times are ISO strings in Pacific time. Fields are still editable.

- **Resident.** id, lat, lon, h3, needs (`wheelchair | oxygen | bedbound | no_car | none`), vehicle_types, load_minutes, people, source (`registry | request`), known_at. Registry is a stated fraction of vulnerable residents (Ali's example: 25%). Request records stay invisible until known_at, which includes a delay. **Unknown:** the delay.
- **Vehicle.** id, type, seats, wheelchair_spaces, lat, lon, status (`idle | en_route | loading`)
- **FireOutlook.** t, h3, p_1h, p_2h, p_3h, arrival_p10_min. arrival_p10_min is the pessimistic deadline input.
- **ArrivalWindow.** h3 or building id, earliest plausible arrival, latest plausible arrival. Built from Cal Fire DINS, FIRMS detections, and the official timeline. DINS says which buildings burned. It does not say when.
- **Plan.** t, plan_id, routes (vehicle, stops, eta_min), unreachable, escalated_fire_command, reasons. A route is invalid if any hex could see fire before the vehicle leaves, plus a margin. **Unknown:** the margin. People who can be reached only through those hexes go to fire command and are not dropped.
- **Decision.** plan_id, action, by, t, changes, approval_delay_min. The sweep varies this delay. The live demo still waits for a person.

Fleet size, speeds, loading times, registry fraction, request delay, approval delay, closure rate, and safety margin are published assumptions. Evaluation sweeps the first four. Road blockage and congestion are random closures and slower speeds inside that sweep.

## Where state lives

- Replay frames (fire probabilities, routes, decisions, sweep summaries) are files, precomputed on laptops or Colab. Static playback is the primary demo. Record a backup video.
- DuckDB is available for local analytical reads of those frames.
- Live state is only tool calls, a new help request, a small optimizer rerun, and the approval. That state sits in the FastAPI process and is pushed to the dashboard on a WebSocket.

## API and data paths the MVP needs

- `GET` world state at time t. Resident reads respect known_at. Every other read is filtered to data from before t.
- WebSocket of that state for the dashboard
- `POST` a free-text help request, returning a Resident whose known_at is now plus the delay
- `POST` approve or change a Plan, appending a Decision
- OpenAPI tools the agents call: current outlook, ranked residents, latest plan
- Evaluation driver, offline: run each strategy twice per scenario (true fire path, and forecast), score both against ArrivalWindow, then repeat across the sweep

## Evaluation design

| Piece | Rule |
|---|---|
| Information | Same registry fraction and the same request delays for our planner, the dispatcher heuristic, and any weaker reference |
| Rescue bar | Most urgent first, nearest suitable vehicle |
| Warning time | Compare with the real evacuation-order times |
| Upper bound | Plan using the true fire path. Label it as an upper bound |
| Realistic | Plan using the forecast only. Label it as the realistic case |
| Score | Both are scored on the arrival window. A pickup counts only if it is earlier than the earliest plausible arrival |
| Output | Median and range. Lead with warning lead time and the four levers: information, warning time, fleet size, routing. Include the fleet-size curve |
| Forecast | One event. Report calibration and Brier score as a case study |
| Safety | Contract test: the optimizer must reject routes that enter a hex the vehicle cannot clear in time |

## Hosting

**Unknown which live host is available.** Order: IBM Code Engine on the team account, if it is in the catalog; else Render free tier; else a Cloudflare quick tunnel for development only. The judged link does not depend on that host. Frontend playback: GitHub Pages or Cloudflare Pages. Code and video: GitHub and YouTube. Agent YAML stays in git after the IBM account closes.

## Sources

| Input | Source | Used by |
|---|---|---|
| Roads | OpenStreetMap via osmnx | Optimizer |
| Fire detections | NASA FIRMS VIIRS 375 m | Nowcast and the arrival window |
| Building damage | Cal Fire DINS | Arrival window (which buildings burned) |
| Wind as issued | NOAA HRRR via herbie | Nowcast |
| Age, disability, no-car | Census ACS | Synthetic population |
| Buildings | Microsoft Global Building Footprints | Synthetic population |
| Evacuation order times | After-action reviews and news, hand-mapped | Warning-time comparison |
| Fuel maps | LANDFIRE | Physics model only, out of MVP |
