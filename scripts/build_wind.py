"""Build data/processed/eaton/wind.jsonl from NOAA HRRR surface forecasts.

For every HRRR sfc cycle from 2025-01-07 18:00 UTC to 2025-01-10 08:00 UTC (hourly)
and fxx 0–3, loads 10 m U/V wind components and surface gust, crops to the study box,
and writes one WindForecast record per grid cell per forecast.

    uv run python scripts/build_wind.py          # all cycles
    uv run python scripts/build_wind.py --quick  # first 3 cycles only (for testing)
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np

from backend.clock import PACIFIC
from backend.schemas import WindForecast
from backend.store import DATASETS, write_jsonl

# PLACEHOLDER: minutes after the HRRR cycle time before the forecast is published on AWS.
# Typical operational latency is ~45-60 min; verify against evaluation results.
HRRR_PUBLISH_LAG_MIN = 60

# Study bounding box (Western Eaton fire area)
W, S, E, N = -118.23, 34.12, -118.03, 34.26

# Full run window: 2025-01-07 18:00 UTC to 2025-01-10 08:00 UTC, every hour
_UTC = UTC
RUN_START = datetime(2025, 1, 7, 18, 0, tzinfo=_UTC)
RUN_END = datetime(2025, 1, 10, 8, 0, tzinfo=_UTC)

HRRR_CACHE_DIR = Path("data/raw/hrrr")

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)


def _cycles() -> list[datetime]:
    """Return every hourly HRRR cycle from RUN_START to RUN_END inclusive."""
    out: list[datetime] = []
    t = RUN_START
    while t <= RUN_END:
        out.append(t)
        t += timedelta(hours=1)
    return out


def _load_cycle(cycle: datetime, fxx: int) -> list[WindForecast]:
    """Fetch one HRRR sfc cycle/fxx and return WindForecast records for every grid cell
    inside the study box. Returns [] and logs a warning if the file is unavailable."""
    from herbie import Herbie  # lazy import; optional dependency

    cycle_str = cycle.strftime("%Y-%m-%d %H:%M")
    try:
        H = Herbie(
            cycle_str,
            model="hrrr",
            product="sfc",
            fxx=fxx,
            save_dir=str(HRRR_CACHE_DIR),
        )
        ds_uv = H.xarray(":(?:UGRD|VGRD):10 m above ground", remove_grib=False)
        ds_gust = H.xarray(":GUST:surface", remove_grib=False)
    except Exception as exc:
        log.warning("Skipping cycle %s fxx=%d: %s", cycle_str, fxx, exc)
        return []

    # Convert HRRR 0–360 longitudes to −180..180
    lon_raw = ds_uv["longitude"].values.copy()
    lon_180 = np.where(lon_raw > 180, lon_raw - 360, lon_raw)
    lat_arr = ds_uv["latitude"].values

    # Crop to study box
    mask2d = (lon_180 >= W) & (lon_180 <= E) & (lat_arr >= S) & (lat_arr <= N)
    if not mask2d.any():
        log.warning("Study box returned 0 grid cells for cycle %s fxx=%d", cycle_str, fxx)
        return []

    rows, cols = np.where(mask2d)
    r0, r1 = int(rows.min()), int(rows.max()) + 1
    c0, c1 = int(cols.min()), int(cols.max()) + 1

    lon_box = lon_180[r0:r1, c0:c1]
    lat_box = lat_arr[r0:r1, c0:c1]

    # Resolve cfgrib variable names (u10 / v10 style)
    uv_vars = list(ds_uv.data_vars)
    u_name = next((v for v in uv_vars if v.startswith("u")), uv_vars[0])
    v_name = next((v for v in uv_vars if v.startswith("v")), uv_vars[1])

    u_box = ds_uv[u_name].values[r0:r1, c0:c1]
    v_box = ds_uv[v_name].values[r0:r1, c0:c1]

    # Gust variable name varies; find it
    import xarray as xr

    ds_wind = xr.merge([ds_uv, ds_gust])
    gust_vars = [v for v in ds_wind.data_vars if "gust" in str(v).lower()]
    if not gust_vars:
        log.warning(
            "No gust variable found for cycle %s fxx=%d; gust_ms will be None", cycle_str, fxx
        )
    gust_box = ds_wind[gust_vars[0]].values[r0:r1, c0:c1] if gust_vars else None

    # Keep only grid points strictly inside the study box (the rectangular slice
    # may include edge cells outside the diagonal HRRR grid boundary).
    inbox = (lon_box >= W) & (lon_box <= E) & (lat_box >= S) & (lat_box <= N)

    # Drop any point with NaN u, v, or gust
    valid_uv = ~np.isnan(u_box) & ~np.isnan(v_box)
    valid_gust = ~np.isnan(gust_box) if gust_box is not None else np.ones_like(inbox, dtype=bool)
    keep = inbox & valid_uv & valid_gust

    n_keep = int(keep.sum())
    if n_keep == 0:
        log.warning("0 valid grid points after filtering for cycle %s fxx=%d", cycle_str, fxx)
        return []
    log.info(
        "  cycle %s fxx=%d → %d points after bbox+NaN filter",
        cycle_str, fxx, n_keep,
    )

    # Derived fields
    speed_ms = np.hypot(u_box, v_box)
    # Meteorological FROM direction: the direction the wind is blowing FROM
    dir_from_deg = (np.degrees(np.arctan2(-u_box, -v_box)) + 360) % 360

    # Timestamps
    issued_at_utc = cycle + timedelta(minutes=HRRR_PUBLISH_LAG_MIN)
    valid_at_utc = cycle + timedelta(hours=fxx)
    issued_at = issued_at_utc.astimezone(PACIFIC)
    valid_at = valid_at_utc.astimezone(PACIFIC)

    records: list[WindForecast] = []
    nrows, ncols = lon_box.shape
    for ri in range(nrows):
        for ci in range(ncols):
            if not keep[ri, ci]:
                continue
            gust = float(gust_box[ri, ci]) if gust_box is not None else None
            records.append(
                WindForecast(
                    issued_at=issued_at,
                    valid_at=valid_at,
                    lat=round(float(lat_box[ri, ci]), 6),
                    lon=round(float(lon_box[ri, ci]), 6),
                    speed_ms=float(speed_ms[ri, ci]),
                    dir_from_deg=float(dir_from_deg[ri, ci]) % 360,
                    gust_ms=gust,
                )
            )
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Process only the first 3 cycles (fast test mode)",
    )
    args = parser.parse_args()

    cycles = _cycles()
    if args.quick:
        cycles = cycles[:3]
        log.info("--quick: running %d cycles only", len(cycles))
    else:
        log.info("Running %d cycles × 4 fxx values", len(cycles))

    HRRR_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    all_records: list[WindForecast] = []
    for cycle in cycles:
        cycle_recs: list[WindForecast] = []
        for fxx in range(4):  # 0, 1, 2, 3
            recs = _load_cycle(cycle, fxx)
            cycle_recs.extend(recs)
        all_records.extend(cycle_recs)
        log.info(
            "cycle %s → %d points across fxx 0-3",
            cycle.strftime("%Y-%m-%dT%H:%MZ"),
            len(cycle_recs),
        )

    out_path = DATASETS["eaton"] / "wind.jsonl"
    write_jsonl(out_path, all_records)
    log.info("Wrote %d WindForecast records → %s", len(all_records), out_path)

    if not all_records:
        log.warning("No records written — all cycles were skipped or returned empty grids.")


if __name__ == "__main__":
    main()
