# Building the real Eaton dataset

Each file in `data/processed/eaton/` comes from one Trello card. Every card writes its file in the
layout from `data/README.md`, so the backend switches from fake to real with
`OUTRUN_DATASET=eaton` and **no code changes**.

**Gate: Oct 12.** By then the whole night replays on real data. One area only. Other counties are
out of scope.

| File | Card | Owner | Source | Notes |
|---|---|---|---|---|
| `detections.jsonl` | Eaton detections and wind | Daniel | NASA FIRMS (VIIRS); NOAA GOES | Set `available_at` to when each detection was published. Check first what GOES saw over west Altadena 22:00–03:25 |
| `wind.jsonl` | Eaton detections and wind | Daniel | NOAA HRRR via `herbie` | `issued_at` = when the forecast run was available |
| `fire_reports.jsonl` | (suggested card) | Bhavaani | FSRI and county investigation timelines | Hand-extract time, place, words and citation (with page) into a CSV, then geocode. Set `location_precision_m` honestly: a street is about 250 m, an area about 1 km |
| `evac_orders.jsonl` | Arrival window | Bhavaani | McChrystal review, news timelines | Real zones and times, one citation per row |
| `dins.geojson` | Arrival window | Bhavaani | CAL FIRE DINS | Scoring only. Never loaded by the replay. Keep the `DAMAGE` column |
| `arrival_window.jsonl` | Arrival window | Bhavaani | derived: `make arrival-window` | Earliest and latest plausible arrival per reached hex (`evaluation/arrival_window.py`). Rebuild after detections, reports or DINS change |
| `residents.jsonl` | Synthetic residents | Rachel | Census ACS + Microsoft building footprints | `source: "estimated"`. Who is known when is applied at load by `backend/knowledge.py` |
| `facilities.jsonl` (+ facility residents) | Synthetic residents | Rachel | CA Community Care Licensing | Licensed capacity; a needs mix per facility type |
| `roads.graphml` | Roads and a first route map | Rachel | OpenStreetMap via `osmnx` | Too big for git |
| `vehicles.jsonl`, `shelters.jsonl` | Roads and a first route map | Rachel | `backend/assumptions.py`; real shelter locations from news | Cite the shelters |
| `meta.json` | Replay clock API | Ali | | `"synthetic": false`; study area = Altadena boundary + 1 km |

Scripts go in `scripts/` (e.g. `scripts/build_detections.py`) and write to `data/processed/eaton/`.
Raw downloads go in `data/raw/`, which is not committed. Every source goes in `DATA_SOURCES.md`.