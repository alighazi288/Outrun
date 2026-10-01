# dashboard/: the emergency manager's screen (built with Bob)

**Build it in Bob IDE and screenshot every session.** This is the most visible
"built with Bob" piece in the video.

## What the user sees

One screen for a county emergency manager at night, under pressure, with a few vehicles:

1. **Map** (MapLibre + OpenFreeMap base map, no API key):
   - fire outlook as H3 hexagons coloured by `p_1h` / `p_2h` / `p_3h` (toggle), burning cells darker
   - **fire reports** (from calls and radio) and satellite detections, styled differently
   - **care facilities** with their resident counts
   - residents coloured by priority; a ring marks escalations (`unreachable`)
   - vehicle routes with numbered stops; shelters
   - evacuation order zones (only those issued by t)
2. **Timeline scrubber** from 18:00 to 06:00 with play/pause and a clear "known at t" label.
3. **Approval panel**:
   - the plan's routes, with each person's reason
   - escalations in red, split into "too late" and "only reachable through danger: fire command"
   - Approve / Modify / Reject buttons that POST to `/decisions`
4. **Chat panel**: the embedded watsonx Orchestrate chat (the Dispatch agent).
5. **An honest footer:** "Fire reports, satellites, roads, care facilities and order times are real.
   Homebound residents and their calls are simulated from Census counts." Plus the attributions in
   `DATA_SOURCES.md`.

Design for the real user: dark theme, big readable numbers, the most urgent thing first, no clutter.

## Data it reads

- **Static replay (the public prototype):** `replay/manifest.json` and `replay/steps/NNNN.json`,
  each a `WorldState` (`residents`, `facilities`, `reports`, `detections`, `outlook`, `risks`,
  `plan`, `orders`, ...).
  ```bash
  uv run outrun-export --out dashboard/public/replay
  ```
- **Live API (demo extras):** `GET /state?t=`, `POST /decisions`, `POST /requests`, `POST /reports`,
  and `ws://localhost:8000/ws`.
- **Types:** generated from the contract:
  ```bash
  npx openapi-typescript ../backend/openapi.json -o src/api-types.ts
  ```

## Tech

React + Vite + TypeScript, `maplibre-gl`, deck.gl (`H3HexagonLayer`, `ScatterplotLayer`,
`PathLayer`, `IconLayer`) via `@deck.gl/mapbox`'s `MapboxOverlay`. Base map:
`https://tiles.openfreemap.org/styles/liberty` (or a dark style). Host on GitHub Pages or
Cloudflare Pages.
