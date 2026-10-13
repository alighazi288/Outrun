# Data sources

IBM requires a list of every website we use, and several sources require attribution. Every
source here is free and public. **No personal information: real addresses and 911 records are not
used; homebound residents are estimated from Census counts.**

Add a row the moment you start using a new source. Replace every `TODO` with the exact URL.

## Data we load

| Data | Source | License / terms | How we get it | Used by |
|---|---|---|---|---|
| Fire reports with times and places | [FSRI Southern California Fires Timeline Report](https://fsri.org/research-update/southern-california-fires-timeline-report) (20 Nov 2025; street names also in the [LAT write-up](https://www.latimes.com/california/story/2025-11-20/state-report-alarms-eaton-fire-evacuations)), [McChrystal after-action review](https://file.lacounty.gov/SDSInter/lac/1192777_AAR_EatonFireSynopsisofFindingsandTimeline.pdf), [Citygate investigation](https://file.lacounty.gov/SDSInter/lac/1208708_InvestigationReportoftheEatonFireEvacuationAlerts_05-18-26_.pdf) ([county release](https://recovery.lacounty.gov/2026/05/18/county-of-los-angeles-fire-department-releases-independent-investigation-findings-of-west-altadena-evacuation-decisions/)) | public reports, cited per record | hand-extracted into `fire_reports.jsonl`; intersections geocoded with the US Census Bureau geocoder | nowcast, ground truth, call triggers |
| Satellite fire detections (VIIRS) | [NASA FIRMS](https://firms.modaps.eosdis.nasa.gov) | NASA open data, cite FIRMS | archive download or area API; free map key | nowcast, ground truth |
| ↳ VIIRS note | SNPP and NOAA-20 rows use the reprocessed **_SP** archive, which did not exist on the night of the fire (only NRT was available then). The replay treats them as available after `FIRMS_LATENCY_MIN`; pixel positions may differ slightly from NRT. | | | |
| Satellite fire detections (GOES-18) | [NOAA GOES on AWS Open Data](https://registry.opendata.aws/noaa-goes/) | public domain (US government) | **ABI-L2-FDCC** (Fire (Hot Spot Characterization)) product files | nowcast, ground truth |
| Which buildings burned | [CAL FIRE DINS 2025 Eaton](https://data.lacounty.gov/datasets/CALFIRE-Forestry::dins-2025-eaton-public-view) ([also on data.ca.gov](https://data.ca.gov/dataset/eaton-fire-structure-status)) | public | ArcGIS query, `scripts/build_dins.py` (18,428 records; 16,646 in the study box) | ground truth only |
| Where the fire started | [LA County, Eaton_Start_Location](https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services/Eaton_Start_Location/FeatureServer/34) | public (LA County open data) | one point, copied into `scripts/eaton_timeline.py` | the 6:18 p.m. origin report |
| Licensed care facilities | [CA Community Care Licensing facilities](https://data.chhs.ca.gov/dataset/ccl-facilities) | public | CSV download (locations, licensed capacity) | who needs help |
| Licensed nursing and health facilities | [CDPH Licensed Healthcare Facility Listing, Dec 31, 2024](https://data.chhs.ca.gov/dataset/licensed-healthcare-facility-listing) | public | CSV snapshot one week before the fire (beds, coordinates) | who needs help |
| Evacuation shelters and when they opened | [City of Pasadena timeline, Council Jan 13, 2025](https://ww2.cityofpasadena.net/2025%20Agendas/Jan_13_25/AR%203%20PPT.pdf) ("8:00 pm: Convention Center agrees to host evacuation center"), [CAL FIRE incident updates](https://www.fire.ca.gov/incidents/2025/1/7/eaton-fire/updates/74cee001-c0c2-4c15-9aee-f7a677402228) | public, cited per record | hand-entered in `scripts/build_shelters.py`; locations from OpenStreetMap | router (drop-off points) |
| Rescue fleet: buses, vans, yard | 11 buses that night: [LAist](https://laist.com/news/health/eaton-fire-bus-drivers-evacuation-nursing-home-assisted-living-care-facility-altadena-pasadena-transit), [CBS Los Angeles](https://www.cbsnews.com/losangeles/news/pasadena-bus-drivers-rushed-into-the-eaton-fire-to-save-500-seniors), McChrystal review (above). Bus capacity: [New Flyer Xcelsior brochure](https://www.newflyer.com/site-content/uploads/sites/2/2021/01/Xcelsior-Family-Brochure_2021.pdf). Van capacity: [City of Pasadena, Apr 8 2024](https://ww2.cityofpasadena.net/2024%20Agendas/Apr_08_24/AR%2010.pdf). Yard: 303 N Allen Ave ([Streetsblog LA](https://la.streetsblog.org/2023/02/28/pasadena-transits-ambitious-zero-emission-bus-rollout-hinges-on-new-operations-facility/)) | cited facts | `scripts/build_vehicles.py`; van and ambulance counts are assumptions (`FLEET_BASELINE`) | router |
| Wind forecasts as issued | [NOAA HRRR on AWS Open Data](https://registry.opendata.aws/noaa-hrrr-pds/) | public domain (US government) | [`herbie`](https://github.com/blaylockbk/Herbie) Python package | nowcast |
| Road network | [OpenStreetMap](https://www.openstreetmap.org) | ODbL 1.0, attribution required | `osmnx` drive network; `scripts/build_roads.py` precomputes cell-to-cell minutes and routes into `roads.json.gz` | travel times, router, driver-safety rule |
| Age, disability, no-car households | [U.S. Census Bureau, ACS 2019-2023 5-year](https://www2.census.gov/programs-surveys/acs/summary_file/2023/table-based-SF/data/5YRData/) (released Dec 2024, before the fire): B18105 ambulatory difficulty, B01001 age, B08201 household size by vehicles; tract outlines from [TIGERweb](https://tigerweb.geo.census.gov/) | public; API notice below | table-based summary files, no key (`scripts/build_residents.py`) | estimated residents |
| Building outlines (pre-fire) | [LA County, Countywide Building Outlines (2020)](https://services.arcgis.com/RmCCgQtiZLDCtblq/arcgis/rest/services/Countywide_Building_Outlines_(2020)/FeatureServer) (LARIAC). Not Microsoft's footprints: their current release is from 2026 and may miss homes that burned | public (LA County open data) | ArcGIS REST query (`scripts/build_residents.py`) | placing estimated residents |
| Evacuation alerts: times, wording, areas | [LA County, IPAWS Jan 2025 Fire Alerts](https://services.arcgis.com/RmCCgQtiZLDCtblq/ArcGIS/rest/services/IPAWS_Jan_2025_Fire_Alerts/FeatureServer/2) (every emergency alert sent to phones, with its area); zone names from Citygate (above) | public (LA County open data) | `scripts/build_evac_orders.py` downloads the alerts; one row per alert that reached the study area, kind from its words (advisory / warning / order) | real response, call triggers, warning lead time |
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
| Two homebound disabled men died despite three 911 calls | [LAist](https://laist.com/news/climate-environment/despite-three-911-calls-two-homebound-disabled-men-died-in-the-eaton-fire-waiting-for-rescue) |

## Assumed, not sourced

Van and ambulance counts, speeds in smoke, loading and approval times, call behaviour, the
safety margin, care-home occupancy and needs mix, and the home-oxygen rate are assumptions about
a response that never happened. They're listed with their status and tested ranges in
`backend/assumptions.py`. Sourced so far: the 11 buses, the wheelchair and homebound rates.
When an owner finds a source, it's added here and the status changes to `SOURCED`.

## Attribution text (dashboard footer and write-up)

- Map data © OpenStreetMap contributors, available under the Open Database License (ODbL).
- Building outlines: Los Angeles County (LARIAC, 2020).
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
