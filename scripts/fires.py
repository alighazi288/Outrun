"""The fires Outrun builds datasets for, and what the builders download for each.

The builders take `--fire` (default eaton) and read everything fire-specific from here, so the
same code builds the Eaton test set and the Palisades development set, and later an area for
live mode. Eaton's values are the ones the builders always used.

- eaton: the test set. The evaluation's claims come from it; nothing is tuned on it.
- palisades: the development set (EVAL_SPEC §8, §12). Same night, same kinds of data, a
  different fire: forecast settings are chosen here, then Eaton is run once.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.clock import PACIFIC
from backend.store import DATA_DIR, DATASETS, EATON_DOWNLOAD_BOX

CAL_FIRE_INCIDENTS = "https://incidents.fire.ca.gov/umbraco/api/IncidentApi/List?inactive=true&year=2025"


@dataclass(frozen=True)
class Fire:
    name: str
    ignition: datetime  # detections before this are dropped; lower bound of arrival windows
    ignition_source: str
    origin: tuple[float, float]  # (lat, lon) where the fire started
    box: dict  # FIRMS, GOES and HRRR download box: west, south, east, north
    goes_utc: tuple[str, str]  # GOES-18 scans to download, UTC "YYYY-MM-DD HH:MM"
    hrrr_utc: tuple[datetime, datetime]  # first and last hourly HRRR cycle, UTC
    dins_layer: str  # CAL FIRE damage inspection layer (scoring only)
    static_sources: tuple[tuple[float, float], ...] = ()  # heat seen every night before ignition

    @property
    def folder(self) -> Path:
        return DATASETS[self.name]

    @property
    def raw_viirs(self) -> Path:
        return DATA_DIR / "raw" / "firms" / f"viirs_{self.name}_2025-01-07_to_10.csv"


FIRES = {
    "eaton": Fire(
        name="eaton",
        ignition=datetime(2025, 1, 7, 18, 18, tzinfo=PACIFIC),
        ignition_source="McChrystal after-action review timeline (DATA_SOURCES.md)",
        origin=(34.185961, -118.093668),  # LA County Eaton_Start_Location
        box=EATON_DOWNLOAD_BOX,
        goes_utc=("2025-01-08 02:00", "2025-01-08 14:00"),
        hrrr_utc=(datetime(2025, 1, 7, 18, tzinfo=UTC), datetime(2025, 1, 10, 8, tzinfo=UTC)),
        dins_layer="DINS_2025_Eaton_Public_View",
        static_sources=((34.153, -118.193),),
    ),
    "palisades": Fire(
        name="palisades",
        # CAL FIRE incident record: Started 2025-01-07T18:30:00Z, 34.07022, -118.54453.
        ignition=datetime(2025, 1, 7, 10, 30, tzinfo=PACIFIC),
        ignition_source=f"CAL FIRE incident record, Palisades Fire ({CAL_FIRE_INCIDENTS})",
        origin=(34.07022, -118.54453),
        # The damage inspections' extent (34.030-34.129 N, 118.499-118.686 W) plus 2 km.
        box={"west": -118.7076, "south": 34.0118, "east": -118.4772, "north": 34.1468},
        # 10:00 Jan 7 to 16:00 Jan 8 Pacific: ignition, the first night, the next day.
        goes_utc=("2025-01-07 18:00", "2025-01-09 00:00"),
        # From the 08:00 run (usable at 09:00) to the run covering the end.
        hrrr_utc=(datetime(2025, 1, 7, 16, tzinfo=UTC), datetime(2025, 1, 9, 0, tzinfo=UTC)),
        dins_layer="DINS_2025_Palisades_Public_View",
    ),
}


def fire_arg(parser) -> None:
    """Add `--fire` to a builder's argument parser."""
    parser.add_argument("--fire", choices=sorted(FIRES), default="eaton",
                        help="which fire's dataset to build (default: eaton)")
