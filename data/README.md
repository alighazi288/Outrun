# data/

## The dataset contract (Proposed)

Every dataset is one folder with the same files, so the backend reads fake and real data the same way.

| File | One line = | Schema (`backend/schemas.py`) | Time field that controls visibility |
|---|---|---|---|
| `meta.json` | (one object) | see below | none |
| `residents.jsonl` | one person who may need help | `Resident`, `source` = `facility` or `estimated` | set at load by `backend/knowledge.py` |
| `facilities.jsonl` | one licensed care facility | `Facility` | none (known up front) |
| `fire_reports.jsonl` | one report of fire (from the published timelines) | `FireReport` | `reported_at` |
| `detections.jsonl` | one satellite detection (VIIRS, GOES) | `FireDetection` | `available_at`, else `observed_at` |
| `wind.jsonl` | one forecast value | `WindForecast` | `issued_at` |
| `evac_orders.jsonl` | one real warning/order | `EvacOrder` | `issued_at` |
| `vehicles.jsonl`, `shelters.jsonl` | fleet and drop-off points | `Vehicle`, `Shelter` | none |
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
