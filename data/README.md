# data/

## The dataset contract (locked 2026-10-05)

Every dataset is one folder with the same files, so the backend reads fake and real data the same way.
**Files hold facts only.** Assumed publish delays live in `backend/assumptions.py` and are applied when
a record is read, so the evaluation can test other delays without rebuilding any file.

| File | One line = | Schema (`backend/schemas.py`) | Time field that controls visibility |
|---|---|---|---|
| `meta.json` | (one object) | see below | none |
| `study_area.geojson` (real data) | the area's real outline (Census), for clipping residents and drawing the map | GeoJSON | none |
| `residents.jsonl` | one person who may need help | `Resident`, `source` = `facility` or `estimated` | set at load by `backend/knowledge.py` |
| `facilities.jsonl` | one licensed care facility | `Facility` | none (known up front) |
| `fire_reports.jsonl` | one report of fire (from the published timelines) | `FireReport` | `reported_at` |
| `detections.jsonl` | one satellite detection (VIIRS, GOES) | `FireDetection`: set `pixel_m` (375 VIIRS, ~2000 GOES); `confidence` is `low`/`nominal`/`high` | `available_at` only if the source records it; else `observed_at` + the assumed delay for its satellite |
| `wind.jsonl` | one forecast value at one grid point | `WindForecast`: set `run_at`; directions relative to true north | `issued_at` only if the source records it; else `run_at` + the assumed HRRR delay |
| `evac_orders.jsonl` | one real warning/order (a zone in several pieces = several lines, same `zone_id`) | `EvacOrder` | `issued_at` |
| `vehicles.jsonl` | one vehicle | `Vehicle` | none |
| `shelters.jsonl` | one drop-off point, with a citation | `Shelter` | `opened_at` (none = open before the fire) |
| `dins.geojson` (real data only) | which buildings burned | for scoring only | never loaded by the replay |

**`residents.jsonl` is the whole population**, the truth the evaluation scores against. Who the
planner knows about, and from when, is applied when the dataset loads (`backend/knowledge.py`):
- Facility residents are known from the start.
- A share of estimated residents are on a list.
- Everyone else becomes known only through a simulated help call.

`DataStore.population` holds everyone; `DataStore.residents` holds who the planner can know about.

`meta.json`:

```json
{
  "name": "eaton",
  "synthetic": false,
  "description": "Eaton Fire: real reports, satellites, wind, roads, facilities, orders; residents estimated from Census",
  "bbox": {"south": 34.160, "west": -118.180, "north": 34.215, "east": -118.080},
  "h3_res": 9,
  "replay": {"start": "2025-01-07T18:00:00-08:00", "end": "2025-01-08T06:00:00-08:00", "step_minutes": 10}
}
```

Road networks and caches (`.graphml`, `.parquet`) go in the same folder; they're gitignored.

## Folders

| Folder | What | In git? |
|---|---|---|
| `fixtures/eaton_fake/` | **Fake** data from `scripts/make_fake_data.py`, including fake fire reports and care homes. Tests and CI only. | yes |
| `raw/` | raw downloads | no |
| `processed/eaton/` | the real Eaton dataset (see `data/BUILD.md`) | small files yes; big ones (roads, caches) no |
| `runs/<run_id>/log.jsonl` | decision log from each API run | no |

## Choosing a dataset

```bash
OUTRUN_DATASET=fixtures uv run outrun-api   # default: fake data
OUTRUN_DATASET=eaton    uv run outrun-api   # real data (after the pipeline has run)
```

**After Oct 11, nothing judges see uses `fixtures`.**
