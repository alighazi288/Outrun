"""Build data/processed/eaton/detections.jsonl from FIRMS VIIRS CSVs and GOES-18 FDCC files.

Downloads VIIRS CSVs from the FIRMS area API if the cache is missing (requires FIRMS_MAP_KEY in
the environment). Downloads GOES-18 ABI-L2-FDCC NetCDF files via goes2go (cached under
data/raw/goes/).  Applies three filters before writing:

  1. Drop type == 2  ("other static land source") – available on SP archive rows only.
  2. Drop any detection within 1 km of (34.153, -118.193) – a static heat source visible
     every night including before ignition (NRT rows carry no type field so we filter by
     location instead; GOES pixels near this spot are filtered the same way).
  3. Drop anything observed before 2025-01-07 18:18 PST (ignition).

FIRMS latency is NOT applied here.  available_at=None for every detection.  The latency offset
is applied at load time by backend/store.py.

Prints row counts and what each filter removed.

Setup:
    uv sync --extra wx
    uv run python scripts/build_detections.py
"""

from __future__ import annotations

import io
import os
import re
import warnings
from datetime import UTC, datetime, timedelta
from pathlib import Path

import h3
import numpy as np
import pandas as pd
import requests
import xarray as xr

from backend.clock import PACIFIC
from backend.schemas import H3_RES, FireDetection
from backend.store import DATASETS, EATON_DOWNLOAD_BOX, write_jsonl
from engines.travel import haversine_m

# Bounding box used for the FIRMS area API download and GOES spatial filter
W = EATON_DOWNLOAD_BOX["west"]
S = EATON_DOWNLOAD_BOX["south"]
E = EATON_DOWNLOAD_BOX["east"]
N = EATON_DOWNLOAD_BOX["north"]

VIIRS_SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT"]

RAW_CSV = Path("data/raw/firms/viirs_eaton_2025-01-07_to_10.csv")
GOES_DIR = Path("data/raw/goes")

# Static heat source seen every night before ignition (no FIRMS type on NRT rows)
STATIC_SOURCE_LAT = 34.153
STATIC_SOURCE_LON = -118.193
STATIC_SOURCE_RADIUS_M = 1_000.0  # 1 km

# Ignition time: drop anything observed before this
IGNITION = datetime(2025, 1, 7, 18, 18, tzinfo=PACIFIC)

# Source name the schema uses; map from the satellite shortcode in the CSV
_SAT_TO_SOURCE = {
    "N":   "VIIRS_SNPP",
    "N20": "VIIRS_NOAA20",
    "N21": "VIIRS_NOAA21",
}

# GOES FDCC fire mask codes and their confidence mapping
# 10/30 = high, 11-13/31-33 = nominal, 14-15/34-35 = low
_FIRE_MASK_CODES = set(range(10, 16)) | set(range(30, 36))

# VIIRS confidence letter -> schema word
_VIIRS_CONF = {"l": "low", "n": "nominal", "h": "high"}


def _confidence_for_mask(code: int) -> str:
    """Return schema confidence word for a GOES fire-mask code."""
    if code in (10, 30):
        return "high"
    if code in range(11, 14) or code in range(31, 34):
        return "nominal"
    return "low"


# ──────────────────────────────────────────────────────────────────────────────
# FIRMS VIIRS download
# ──────────────────────────────────────────────────────────────────────────────

def download_csv() -> None:
    """Download VIIRS detections from the FIRMS area API and save to RAW_CSV.

    Raises SystemExit if any source returns a non-CSV response so the partial
    cache is never written.
    """
    key = os.environ["FIRMS_MAP_KEY"]
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for source in VIIRS_SOURCES:
        url = (
            f"https://firms.modaps.eosdis.nasa.gov/api/area/csv"
            f"/{key}/{source}/{W},{S},{E},{N}/4/2025-01-07"
        )
        print(f"  Fetching {source} …")
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        text = resp.text.strip()
        if not text or not text.startswith("latitude"):
            print(f"  ↳ Non-CSV response for {source}: {text[:200]}")
            raise SystemExit(
                f"Non-CSV response from FIRMS for {source} – cache not written."
            )
        df = pd.read_csv(io.StringIO(text))
        df["firms_source"] = source
        print(f"  ↳ {len(df):,} rows")
        frames.append(df)
    if not frames:
        raise SystemExit("No data returned from any FIRMS source — check FIRMS_MAP_KEY and bbox")
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(RAW_CSV, index=False)
    print(f"Saved {len(combined):,} rows → {RAW_CSV}")


def load_and_parse() -> pd.DataFrame:
    """Read the raw CSV and add observed_at (Pacific)."""
    df = pd.read_csv(RAW_CSV)
    # acq_time is an integer like 130 (= 01:30 UTC) – zero-pad to 4 digits
    acq_time_str = df["acq_time"].astype(int).astype(str).str.zfill(4)
    df["observed_at"] = pd.to_datetime(
        df["acq_date"] + " " + acq_time_str.str[:2] + ":" + acq_time_str.str[2:],
        utc=True,
    ).dt.tz_convert(PACIFIC)
    return df


def build_viirs_detection(row: pd.Series) -> FireDetection:
    lat = float(row["latitude"])
    lon = float(row["longitude"])
    source_tag = _SAT_TO_SOURCE.get(str(row["satellite"]), str(row["satellite"]))
    acq_date = str(row["acq_date"])
    acq_time = str(int(row["acq_time"])).zfill(4)
    observed_at = row["observed_at"].to_pydatetime()
    frp = float(row["frp"]) if pd.notna(row["frp"]) else None
    raw_conf = str(row["confidence"]).strip().lower() if pd.notna(row["confidence"]) else None
    confidence = _VIIRS_CONF.get(raw_conf) if raw_conf is not None else None
    return FireDetection(
        id=f"{source_tag}_{acq_date}_{acq_time}_{lat:.4f}_{lon:.4f}",
        lat=lat,
        lon=lon,
        h3=h3.latlng_to_cell(lat, lon, H3_RES),
        observed_at=observed_at,
        available_at=None,
        source=source_tag,
        frp_mw=frp,
        confidence=confidence,
    )


# ──────────────────────────────────────────────────────────────────────────────
# GOES-18 ABI-L2-FDCC download and parsing
# ──────────────────────────────────────────────────────────────────────────────

def _file_time_utc(path: str) -> datetime | None:
    """Parse scan start time from a GOES filename.

    Filename contains a field like _s20250080600173 where:
      YYYY = year, DDD = day-of-year, HH = hour, MM = minute, SS = second.
    """
    name = Path(path).name
    m = re.search(r"_s(\d{14})", name)
    if not m:
        return None
    s = m.group(1)
    return datetime(int(s[:4]), 1, 1, tzinfo=UTC) + timedelta(
        days=int(s[4:7]) - 1,
        hours=int(s[7:9]),
        minutes=int(s[9:11]),
        seconds=int(s[11:13]),
    )


def _goes_latlon(ds: xr.Dataset) -> tuple[np.ndarray, np.ndarray]:
    """Return (lon2d, lat2d) arrays for a GOES ABI file using pyproj."""
    import pyproj  # optional dependency; only imported when needed

    proj_var = ds["goes_imager_projection"]
    h     = float(proj_var.attrs["perspective_point_height"])
    lon0  = float(proj_var.attrs["longitude_of_projection_origin"])
    sweep = proj_var.attrs["sweep_angle_axis"]
    a     = float(proj_var.attrs["semi_major_axis"])
    b     = float(proj_var.attrs["semi_minor_axis"])

    p = pyproj.Proj(proj="geos", h=h, lon_0=lon0, sweep=sweep, a=a, b=b)

    x_m = ds["x"].values * h
    y_m = ds["y"].values * h
    xx, yy = np.meshgrid(x_m, y_m)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lon2d, lat2d = p(xx, yy, inverse=True)

    lon2d = np.where(np.abs(lon2d) > 360, np.nan, lon2d)
    lat2d = np.where(np.abs(lat2d) > 90,  np.nan, lat2d)
    return lon2d, lat2d


def download_goes() -> list[str]:
    """Download GOES-18 ABI-L2-FDCC files for the study window and return local paths.

    Window: 2025-01-07 18:00 PST – 2025-01-08 06:00 PST
           = 2025-01-08 02:00 UTC – 2025-01-08 14:00 UTC
    Files are cached under data/raw/goes/.
    """
    from goes2go import GOES  # optional dependency

    GOES_DIR.mkdir(parents=True, exist_ok=True)
    g = GOES(satellite=18, product="ABI-L2-FDCC", domain="C")
    dl = g.timerange(
        start="2025-01-08 02:00",
        end="2025-01-08 14:00",
        save_dir=str(GOES_DIR),
        return_as="filelist",
    )
    local_files = [str(GOES_DIR / row) for row in dl["file"]]
    print(f"  GOES-18 FDCC: {len(local_files)} files downloaded/cached → {GOES_DIR}")
    return local_files


def build_goes_detections(local_files: list[str]) -> list[FireDetection]:
    """Parse each GOES NetCDF file and return FireDetection records for fire pixels.

    Keeps pixels with Mask in 10-15 or 30-35 whose centre lies inside W/S/E/N.
    """
    records: list[FireDetection] = []
    for fpath in local_files:
        t_utc = _file_time_utc(fpath)
        if t_utc is None:
            print(f"  skip (no timestamp): {Path(fpath).name}")
            continue
        try:
            ds = xr.open_dataset(fpath)
            lon2d, lat2d = _goes_latlon(ds)
            mask_arr = ds["Mask"].values
            power_arr = ds["Power"].values if "Power" in ds else None
            ds.close()
        except Exception as exc:
            print(f"  skip {Path(fpath).name}: {exc}")
            continue

        scan_start = t_utc.astimezone(PACIFIC)

        # Spatial filter: inside bounding box
        in_box = (
            (lon2d >= W) & (lon2d <= E) &
            (lat2d >= S) & (lat2d <= N)
        )

        rows_idx, cols_idx = np.where(in_box)
        for ri, ci in zip(rows_idx, cols_idx, strict=True):
            code = int(mask_arr[ri, ci])
            if code not in _FIRE_MASK_CODES:
                continue
            lat = float(lat2d[ri, ci])
            lon = float(lon2d[ri, ci])
            frp = None
            if power_arr is not None:
                v = float(power_arr[ri, ci])
                frp = v if np.isfinite(v) else None
            records.append(FireDetection(
                id=f"goes18_{scan_start:%Y%m%dT%H%M}_{lat:.4f}_{lon:.4f}",
                lat=lat,
                lon=lon,
                h3=h3.latlng_to_cell(lat, lon, H3_RES),
                observed_at=scan_start,
                available_at=None,
                source="GOES18",
                pixel_m=2000.0,
                frp_mw=frp,
                confidence=_confidence_for_mask(code),
            ))
    return records


# ──────────────────────────────────────────────────────────────────────────────
# Shared filters
# ──────────────────────────────────────────────────────────────────────────────

def _near_static_source(lat: float, lon: float) -> bool:
    return haversine_m((lat, lon), (STATIC_SOURCE_LAT, STATIC_SOURCE_LON)) <= STATIC_SOURCE_RADIUS_M


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    # ── VIIRS ─────────────────────────────────────────────────────────────────
    if not RAW_CSV.exists():
        print(f"Raw CSV not found at {RAW_CSV}, downloading …")
        download_csv()
    else:
        print(f"Using cached CSV: {RAW_CSV}")

    df = load_and_parse()
    total_raw = len(df)
    print(f"\nLoaded {total_raw:,} rows from {RAW_CSV.name}")

    # Filter 1: drop type == 2 ("other static land source")
    type_2_mask = pd.to_numeric(df["type"], errors="coerce") == 2
    n_type2 = int(type_2_mask.sum())
    df = df[~type_2_mask].copy()
    print(f"  Dropped {n_type2:,} rows with type == 2 (other static land source)")

    # Filter 2: drop detections within 1 km of the known static source
    static_mask = df.apply(
        lambda r: _near_static_source(float(r["latitude"]), float(r["longitude"])),
        axis=1,
    )
    n_static = int(static_mask.sum())
    df = df[~static_mask].copy()
    print(
        f"  Dropped {n_static:,} rows within 1 km of "
        f"static source ({STATIC_SOURCE_LAT}, {STATIC_SOURCE_LON})"
    )

    # Filter 3: drop anything before ignition
    before_ignition_mask = df["observed_at"] < IGNITION
    n_pre = int(before_ignition_mask.sum())
    df = df[~before_ignition_mask].copy().reset_index(drop=True)
    print(f"  Dropped {n_pre:,} rows observed before ignition ({IGNITION.isoformat()})")
    print(f"  Remaining VIIRS: {len(df):,} of {total_raw:,} rows")

    viirs_records: list[FireDetection] = []
    for _, row in df.iterrows():
        viirs_records.append(build_viirs_detection(row))
    print(f"\nBuilt {len(viirs_records):,} VIIRS FireDetection records")

    # ── GOES-18 ───────────────────────────────────────────────────────────────
    print("\nDownloading/loading GOES-18 ABI-L2-FDCC …")
    local_goes = download_goes()
    goes_all = build_goes_detections(local_goes)
    print(f"  Raw GOES fire pixels: {len(goes_all):,}")

    # Apply same static-source filter (within 1 km of 34.153, -118.193)
    goes_filtered = [d for d in goes_all if not _near_static_source(d.lat, d.lon)]
    n_goes_static = len(goes_all) - len(goes_filtered)

    # Apply ignition filter
    goes_final = [d for d in goes_filtered if d.observed_at >= IGNITION]
    n_goes_pre = len(goes_filtered) - len(goes_final)

    print(f"  Dropped {n_goes_static:,} GOES pixels near static source")
    print(f"  Dropped {n_goes_pre:,} GOES pixels before ignition")
    print(f"  Remaining GOES: {len(goes_final):,}")

    # ── Merge, sort, write ────────────────────────────────────────────────────
    all_records: list[FireDetection] = viirs_records + goes_final
    all_records.sort(key=lambda d: d.observed_at)

    out_dir = DATASETS["eaton"]
    out_path = out_dir / "detections.jsonl"
    write_jsonl(out_path, all_records)

    print(f"\nWrote {len(all_records):,} total detections → {out_path}")
    print(f"  VIIRS: {len(viirs_records):,}")
    print(f"  GOES-18: {len(goes_final):,}")

    if goes_final:
        first_goes = min(goes_final, key=lambda d: d.observed_at)
        print(f"  First GOES detection time: {first_goes.observed_at.isoformat()}")
        goes_west = [d for d in goes_final if d.lon < -118.131]
        if goes_west:
            first_west = min(goes_west, key=lambda d: d.observed_at)
            print(
                f"  First GOES detection west of -118.131: {first_west.observed_at.isoformat()} "
                f"({first_west.lat:.4f}, {first_west.lon:.4f})"
            )
        else:
            print("  No GOES detections west of -118.131")

    all_obs = [r.observed_at for r in all_records]
    print(f"  Time range: {min(all_obs).isoformat()}  →  {max(all_obs).isoformat()}")


if __name__ == "__main__":
    main()
