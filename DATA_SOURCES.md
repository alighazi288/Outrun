# Data sources

Public sources only. Residents are synthetic. Add a row when a new site is used. OpenStreetMap and Microsoft building footprints require attribution.

| Input | Source | How to get it | Used by |
|---|---|---|---|
| Road network | OpenStreetMap | `osmnx` Python package, no key | Route optimizer |
| Fire detections with timestamps | NASA FIRMS VIIRS, 375 m | Archive download or API. Free map key by email | Nowcast, and the arrival window |
| Wind forecasts as issued | NOAA HRRR archive on AWS Open Data | `herbie` Python package, no AWS account | Nowcast |
| Age, disability, no-car households | U.S. Census Bureau, American Community Survey | Census API, free key | Synthetic population |
| Building footprints | Microsoft Global Building Footprints | Free download | Synthetic population |
| Which buildings burned | Cal Fire DINS | Public damage-inspection data. It has no time of arrival | Arrival window |
| Evacuation order times and zones | Official after-action reviews and news timelines | Hand-mapped into a small file in this repo | Warning-time comparison |
| Vegetation fuel maps | LANDFIRE | Free download | Physics fire model only. Out of the MVP |

## Attribution

- Map data from OpenStreetMap, available under the Open Database License.
- Building footprints from Microsoft.

## Not a source

- Real resident names, addresses, or 911 records
- Live alert systems
