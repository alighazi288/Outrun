"""Build data/processed/eaton/detections.jsonl from the raw FIRMS VIIRS CSV.

Downloads the CSV from the FIRMS area API if it is missing (requires FIRMS_MAP_KEY in the
environment). Applies three filters before writing:

  1. Drop type == 2  ("other static land source") – available on SP archive rows only.
  2. Drop any detection within 1 km of (34.153, -118.193) – a static heat source visible
     every night including before ignition (NRT rows carry no type field so we filter by
     location instead).
  3. Drop anything observed before 2025-01-07 18:18 PST (ignition).

Prints row counts and what each filter removed.

    uv run python scripts/build_detections.py
"""

from __future__ import annotations

import io
import math
import os
from datetime import datetime, timedelta
from pathlib import Path

import h3
import pandas as pd
import requests

from backend.clock import PACIFIC
from backend.schemas import FireDetection
from backend.store import DATASETS, write_jsonl

# PLACEHOLDER: FIRMS US real-time latency, to verify; evaluation should test 15, 30, 180
FIRMS_LATENCY_MIN = 30

# Bounding box used for the FIRMS area API download
W, S, E, N = -118.23, 34.12, -118.03, 34.26

VIIRS_SOURCES = ["VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_NRT"]

RAW_CSV = Path("data/raw/firms/viirs_eaton_2025-01-07_to_10.csv")

# Static heat source seen every night before ignition (no FIRMS type on NRT rows)
STATIC_SOURCE_LAT = 34.153
STATIC_SOURCE_LON = -118.193
STATIC_SOURCE_RADIUS_KM = 1.0

# Ignition time: drop anything observed before this
IGNITION = datetime(2025, 1, 7, 18, 18, tzinfo=PACIFIC)

# Source name the schema uses; map from the satellite shortcode in the CSV
_SAT_TO_SOURCE = {
    "N":   "VIIRS_SNPP",
    "N20": "VIIRS_NOAA20",
    "N21": "VIIRS_NOAA21",
}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometres."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def download_csv() -> None:
    """Download VIIRS detections from the FIRMS area API and save to RAW_CSV."""
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
            continue
        df = pd.read_csv(io.StringIO(text))
        df["firms_source"] = source
        print(f"  ↳ {len(df):,} rows")
        frames.append(df)
    if not frames:
        raise RuntimeError("No data returned from any FIRMS source — check FIRMS_MAP_KEY and bbox")
    combined = pd.concat(frames, ignore_index=True)
    combined.to_csv(RAW_CSV, index=False)
    print(f"Saved {len(combined):,} rows → {RAW_CSV}")


def load_and_parse() -> pd.DataFrame:
    """Read the raw CSV and add observed_at (Pacific, with offset)."""
    df = pd.read_csv(RAW_CSV)
    # acq_time is an integer like 130 (= 01:30 UTC) – zero-pad to 4 digits
    acq_time_str = df["acq_time"].astype(int).astype(str).str.zfill(4)
    df["observed_at"] = pd.to_datetime(
        df["acq_date"] + " " + acq_time_str.str[:2] + ":" + acq_time_str.str[2:],
        utc=True,
    ).dt.tz_convert(PACIFIC)
    return df


def build_detection(row: pd.Series, idx: int) -> FireDetection:
    lat = float(row["latitude"])
    lon = float(row["longitude"])
    source_tag = _SAT_TO_SOURCE.get(str(row["satellite"]), str(row["satellite"]))
    observed_at = row["observed_at"].to_pydatetime()
    available_at = observed_at + timedelta(minutes=FIRMS_LATENCY_MIN)
    frp = float(row["frp"]) if pd.notna(row["frp"]) else None
    confidence = str(row["confidence"]) if pd.notna(row["confidence"]) else None
    return FireDetection(
        id=f"viirs_{source_tag}_{idx}",
        lat=lat,
        lon=lon,
        h3=h3.latlng_to_cell(lat, lon, 9),
        observed_at=observed_at,
        available_at=available_at,
        source=source_tag,
        frp_mw=frp,
        confidence=confidence,
    )


def main() -> None:
    if not RAW_CSV.exists():
        print(f"Raw CSV not found at {RAW_CSV}, downloading …")
        download_csv()
    else:
        print(f"Using cached CSV: {RAW_CSV}")

    df = load_and_parse()
    total_raw = len(df)
    print(f"\nLoaded {total_raw:,} rows from {RAW_CSV.name}")

    # --- Filter 1: drop type == 2 ("other static land source") ---------------
    # type is float in SP rows, empty string in NRT rows
    type_2_mask = df["type"].astype(str).str.strip() == "2.0"
    n_type2 = int(type_2_mask.sum())
    df = df[~type_2_mask].copy()
    print(f"  Dropped {n_type2:,} rows with type == 2 (other static land source)")

    # --- Filter 2: drop detections within 1 km of the known static source ----
    distances = df.apply(
        lambda r: _haversine_km(
            float(r["latitude"]), float(r["longitude"]),
            STATIC_SOURCE_LAT, STATIC_SOURCE_LON,
        ),
        axis=1,
    )
    static_mask = distances <= STATIC_SOURCE_RADIUS_KM
    n_static = int(static_mask.sum())
    df = df[~static_mask].copy()
    print(
        f"  Dropped {n_static:,} rows within {STATIC_SOURCE_RADIUS_KM} km of "
        f"static source ({STATIC_SOURCE_LAT}, {STATIC_SOURCE_LON})"
    )

    # --- Filter 3: drop anything before ignition -----------------------------
    before_ignition_mask = df["observed_at"] < IGNITION
    n_pre = int(before_ignition_mask.sum())
    df = df[~before_ignition_mask].copy().reset_index(drop=True)
    print(f"  Dropped {n_pre:,} rows observed before ignition ({IGNITION.isoformat()})")

    print(f"  Remaining: {len(df):,} of {total_raw:,} rows")

    # --- Build pydantic objects (invalid rows raise, loud failure) -----------
    records: list[FireDetection] = []
    for idx, row in df.iterrows():
        records.append(build_detection(row, int(idx)))

    # --- Write ----------------------------------------------------------------
    out_dir = DATASETS["eaton"]
    out_path = out_dir / "detections.jsonl"
    write_jsonl(out_path, records)

    t_min = df["observed_at"].min()
    t_max = df["observed_at"].max()
    print(f"\nWrote {len(records):,} detections → {out_path}")
    print(f"  Time range: {t_min.isoformat()}  →  {t_max.isoformat()}")


if __name__ == "__main__":
    main()
