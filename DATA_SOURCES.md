# Data sources

IBM requires a list of every website we use, and several sources require attribution. Every
source here is free and public. **No personal information: real addresses and 911 records are not
used; homebound residents are estimated from Census counts.**

Add a row the moment you start using a new source. Replace every `TODO` with the exact URL.

## Data we load

| Data | Source | License / terms | How we get it | Used by |
|---|---|---|---|---|
| Fire reports with times and places | [FSRI investigation](https://www.aol.com/news/fire-marched-toward-west-altadena-172627594.html) (TODO: link the report itself), [McChrystal after-action review](https://file.lacounty.gov/SDSInter/lac/1192777_AAR_EatonFireSynopsisofFindingsandTimeline.pdf), [Citygate investigation](https://recovery.lacounty.gov/2026/05/18/county-of-los-angeles-fire-department-releases-independent-investigation-findings-of-west-altadena-evacuation-decisions/) | public reports, cited per record | hand-extracted into `fire_reports.jsonl` | nowcast, ground truth |
| Satellite fire detections (VIIRS) | [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | NASA open data, cite FIRMS | archive download or area API; free map key | nowcast, ground truth |
| Satellite fire detections (GOES, if it covers the night) | [NOAA GOES on AWS Open Data](https://registry.opendata.aws/noaa-goes/) | public domain (US government) | ABI fire product files | nowcast, ground truth |
| Which buildings burned | [CAL FIRE DINS 2025 Eaton](https://data.lacounty.gov/datasets/CALFIRE-Forestry::dins-2025-eaton-public-view) ([also on data.ca.gov](https://data.ca.gov/dataset/eaton-fire-structure-status)) | public | CSV / GeoJSON download (18,428 records) | ground truth |
| Licensed care facilities | [CA Community Care Licensing facilities](https://data.chhs.ca.gov/dataset/ccl-facilities) | public | CSV download (locations, licensed capacity) | who needs help |
| Wind forecasts as issued | [NOAA HRRR on AWS Open Data](https://registry.opendata.aws/noaa-hrrr-pds/) | public domain (US government) | [`herbie`](https://github.com/blaylockbk/Herbie) Python package | nowcast |
| Road network | [OpenStreetMap](https://www.openstreetmap.org) | ODbL 1.0, attribution required | `osmnx` Python package | travel times, router |
| Age, disability, no-car households | [U.S. Census Bureau, American Community Survey](https://www.census.gov/programs-surveys/acs) | public; API notice below | Census API, free key | estimated residents |
| Building footprints | [Microsoft Global ML Building Footprints](https://github.com/microsoft/GlobalMLBuildingFootprints) | ODbL, attribution required | free download | placing estimated residents |
| Evacuation order times and zones | McChrystal review (above), [NBC News](https://www.nbcnews.com/news/us-news/eaton-fire-deaths-los-angeles-evacuation-orders-took-hours-rcna188729), [Washington Post](https://www.washingtonpost.com/weather/interactive/2025/altadena-wildfire-destruction-eaton-fire/) | cited facts | hand-mapped into a small file in this repo | real response, call triggers |
| Base map tiles | [OpenFreeMap](https://openfreemap.org) | free, no key; OpenMapTiles + OSM attribution | style URL | dashboard |
| Map grid | [Uber H3](https://h3geo.org) | Apache 2.0 | `h3` Python package | everything |
| Vegetation fuel maps | [LANDFIRE](https://landfire.gov) | public domain (US government) | free download | physics fire model only; out of the MVP |

## Background we cite (not loaded)

| Fact | Source |
|---|---|
| First VIIRS detection of the Eaton Fire at 1:30 a.m. Jan 8 | [NASA Scientific Visualization Studio](https://svs.gsfc.nasa.gov/5558/) |
| Aircraft grounded at 6:45 p.m.; vehicle shortage; buses to senior facilities | [McChrystal after-action review](https://file.lacounty.gov/SDSInter/lac/1192777_AAR_EatonFireSynopsisofFindingsandTimeline.pdf), [LA County after-action reviews](https://lacounty.gov/aar/) |
| Orders "not delayed" relative to the main front (~5:13 a.m.) | [Citygate, via LA County Fire](https://recovery.lacounty.gov/2026/05/18/county-of-los-angeles-fire-department-releases-independent-investigation-findings-of-west-altadena-evacuation-decisions/), [CBS Los Angeles](https://www.cbsnews.com/losangeles/news/independent-report-finds-that-eaton-fire-evacuation-orders-were-not-delayed/) |
| All 17 deaths west of Lake Avenue | [NBC News](https://www.nbcnews.com/news/us-news/eaton-fire-deaths-los-angeles-evacuation-orders-took-hours-rcna188729) |
| Two homebound disabled men died despite three 911 calls | LAist (TODO URL) |

## Assumed, not sourced

Fleet size, speeds, loading and approval times, call behaviour and the safety margin are
assumptions about a response that never happened. They're listed with their status and tested
ranges in `backend/assumptions.py`. When an owner finds a source,
it's added here and the status changes to `SOURCED`.

## Attribution text (dashboard footer and write-up)

- Map data © OpenStreetMap contributors, available under the Open Database License (ODbL).
- Building footprints © Microsoft, ODbL.
- Fire detections: NASA Fire Information for Resource Management System (FIRMS); NOAA GOES.
- Wind: NOAA High-Resolution Rapid Refresh (HRRR).
- Damage data: CAL FIRE Damage Inspection (DINS). Facility data: California Community Care Licensing.
- This product uses the Census Bureau Data API but is not endorsed or certified by the Census Bureau.

## Not a source

- Real resident names, addresses, or 911 records
- Live alert systems

## Not real data

`data/fixtures/eaton_fake/` is **invented** for development and tests (`scripts/make_fake_data.py`),
including its fire reports and care homes. It is never used in the demo, video or evaluation.
