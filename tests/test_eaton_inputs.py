"""Validate the real Eaton pipeline outputs against schema invariants.

Skipped automatically when the relevant processed file is missing:
- detections tests skip if data/processed/eaton/detections.jsonl is missing
- wind tests skip if data/processed/eaton/wind.jsonl is missing

Run locally after `uv run python scripts/build_detections.py` and
`uv run python scripts/build_wind.py` to verify the processed data.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest

from backend.assumptions import FIRMS_LATENCY_MIN, HRRR_PUBLISH_LAG_MIN
from backend.schemas import FireDetection, WindForecast
from backend.store import DATASETS, EATON_DOWNLOAD_BOX, read_jsonl
from engines.travel import haversine_m

# ---------------------------------------------------------------------------
# Study bounding box – single source of truth
# ---------------------------------------------------------------------------
_W = EATON_DOWNLOAD_BOX["west"]
_S = EATON_DOWNLOAD_BOX["south"]
_E = EATON_DOWNLOAD_BOX["east"]
_N = EATON_DOWNLOAD_BOX["north"]

_EATON_DIR = DATASETS["eaton"]
_DETECTIONS_PATH = _EATON_DIR / "detections.jsonl"
_WIND_PATH = _EATON_DIR / "wind.jsonl"

# ---------------------------------------------------------------------------
# Skip markers
# ---------------------------------------------------------------------------
skip_if_no_detections = pytest.mark.skipif(
    not _DETECTIONS_PATH.exists(),
    reason=f"Eaton detections data not found: {_DETECTIONS_PATH}",
)
skip_if_no_wind = pytest.mark.skipif(
    not _WIND_PATH.exists(),
    reason=f"Eaton wind data not found: {_WIND_PATH}",
)

# Known static heat source that must be excluded from detections
_STATIC_LAT = 34.153
_STATIC_LON = -118.193
_STATIC_RADIUS_M = 1_000.0

# Valid satellite source names (schema list)
_VALID_SOURCES = {"VIIRS_SNPP", "VIIRS_NOAA20", "VIIRS_NOAA21", "GOES18"}

# Valid confidence values
_VALID_CONFIDENCE = {"low", "nominal", "high"}

# Valid fxx offsets for HRRR (0–3 hours)
_VALID_FXX_HOURS = {0, 1, 2, 3}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_tz(dt) -> bool:  # type: ignore[type-arg]
    return dt is not None and dt.tzinfo is not None and dt.utcoffset() is not None


# ---------------------------------------------------------------------------
# Detections
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def detections() -> list[FireDetection]:
    return read_jsonl(_DETECTIONS_PATH, FireDetection)


@skip_if_no_detections
def test_detections_not_empty(detections: list[FireDetection]) -> None:
    assert len(detections) > 0, "detections.jsonl is empty"


@skip_if_no_detections
def test_detections_times_have_tz_offset(detections: list[FireDetection]) -> None:
    bad = [
        d.id
        for d in detections
        if not _has_tz(d.observed_at)
        or (d.available_at is not None and not _has_tz(d.available_at))
    ]
    assert not bad, f"Detections with missing tz offset: {bad[:5]}"


@skip_if_no_detections
def test_detections_available_at_is_none(detections: list[FireDetection]) -> None:
    """Raw detections must have available_at=None; latency is applied at load time."""
    bad = [d.id for d in detections if d.available_at is not None]
    assert not bad, f"Detections with non-None available_at: {bad[:5]}"


@skip_if_no_detections
def test_detections_inside_study_box(detections: list[FireDetection]) -> None:
    bad = [
        d.id
        for d in detections
        if not (_S <= d.lat <= _N and _W <= d.lon <= _E)
    ]
    assert not bad, f"Detections outside study box: {bad[:5]}"


@skip_if_no_detections
def test_detections_valid_sources(detections: list[FireDetection]) -> None:
    """Every detection source must be one of the known satellite sources."""
    bad = [d.id for d in detections if d.source not in _VALID_SOURCES]
    assert not bad, (
        f"Detections with unknown source: {bad[:5]} "
        f"(valid: {sorted(_VALID_SOURCES)})"
    )


@skip_if_no_detections
def test_detections_no_static_heat_source(detections: list[FireDetection]) -> None:
    """No detection must fall within 1 km of the known static heat source."""
    bad = [
        d.id
        for d in detections
        if haversine_m((d.lat, d.lon), (_STATIC_LAT, _STATIC_LON)) <= _STATIC_RADIUS_M
    ]
    assert not bad, (
        f"Detections within 1 km of static source ({_STATIC_LAT}, {_STATIC_LON}): {bad[:5]}"
    )


@skip_if_no_detections
def test_detections_confidence_vocabulary(detections: list[FireDetection]) -> None:
    """confidence must be low/nominal/high (schema words) or None."""
    bad = [
        d.id
        for d in detections
        if d.confidence is not None and d.confidence not in _VALID_CONFIDENCE
    ]
    assert not bad, (
        f"Detections with invalid confidence value: {bad[:5]} "
        f"(valid: {sorted(_VALID_CONFIDENCE)} or None)"
    )


@skip_if_no_detections
def test_goes_detections_pixel_m_2000(detections: list[FireDetection]) -> None:
    """GOES detections must have pixel_m == 2000."""
    bad = [
        d.id
        for d in detections
        if d.source == "GOES18" and d.pixel_m != 2000.0
    ]
    assert not bad, f"GOES detections with pixel_m != 2000: {bad[:5]}"


@skip_if_no_detections
def test_goes_source_name(detections: list[FireDetection]) -> None:
    """Source name for GOES must be 'GOES18', not 'GOES18_FDCC'."""
    bad = [d.id for d in detections if d.source == "GOES18_FDCC"]
    assert not bad, f"Detections still using deprecated source 'GOES18_FDCC': {bad[:5]}"


@skip_if_no_detections
def test_viirs_visible_from_equals_observed_plus_firms_latency(
    detections: list[FireDetection],
) -> None:
    """Every VIIRS row's visible_from() must equal observed_at + FIRMS_LATENCY_MIN."""
    viirs = [d for d in detections if d.source.startswith("VIIRS")]
    bad = [
        d.id
        for d in viirs
        if d.visible_from() != d.observed_at + timedelta(minutes=FIRMS_LATENCY_MIN)
    ]
    assert not bad, (
        f"VIIRS rows where visible_from() != observed_at + {FIRMS_LATENCY_MIN} min: {bad[:5]}"
    )


# ---------------------------------------------------------------------------
# Wind
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def wind() -> list[WindForecast]:
    return read_jsonl(_WIND_PATH, WindForecast)


@skip_if_no_wind
def test_wind_not_empty(wind: list[WindForecast]) -> None:
    assert len(wind) > 0, "wind.jsonl is empty"


@skip_if_no_wind
def test_wind_run_at_set_issued_at_none(wind: list[WindForecast]) -> None:
    """Files use run_at (the cycle time); issued_at must be unset (None)."""
    bad_no_run = [i for i, w in enumerate(wind) if w.run_at is None]
    bad_has_issued = [i for i, w in enumerate(wind) if w.issued_at is not None]
    assert not bad_no_run, f"Wind rows with run_at=None at indices: {bad_no_run[:5]}"
    assert not bad_has_issued, (
        f"Wind rows with issued_at set (should be None) at indices: {bad_has_issued[:5]}"
    )


@skip_if_no_wind
def test_wind_times_have_tz_offset(wind: list[WindForecast]) -> None:
    bad_run = [i for i, w in enumerate(wind) if not _has_tz(w.run_at)]
    bad_valid = [i for i, w in enumerate(wind) if not _has_tz(w.valid_at)]
    assert not bad_run, f"Wind rows with naive run_at at indices: {bad_run[:5]}"
    assert not bad_valid, f"Wind rows with naive valid_at at indices: {bad_valid[:5]}"


@skip_if_no_wind
def test_wind_run_at_on_the_hour(wind: list[WindForecast]) -> None:
    """run_at must be on the hour (seconds == minutes == 0) – HRRR cycle times."""
    bad = [
        i
        for i, w in enumerate(wind)
        if w.run_at.minute != 0 or w.run_at.second != 0 or w.run_at.microsecond != 0
    ]
    assert not bad, (
        f"Wind rows where run_at is not on the hour at indices: {bad[:5]}\n"
        f"  example: {wind[bad[0]].run_at}"
    )


@skip_if_no_wind
def test_wind_fxx_is_0_to_3_hours(wind: list[WindForecast]) -> None:
    """valid_at - run_at must be exactly 0, 1, 2, or 3 hours (HRRR fxx 0–3)."""
    bad = []
    for i, w in enumerate(wind):
        delta = w.valid_at - w.run_at
        hours = delta.total_seconds() / 3600
        if hours not in _VALID_FXX_HOURS:
            bad.append((i, hours))
    assert not bad, (
        f"Wind rows where valid_at - run_at is not in {{0,1,2,3}} h: "
        f"{bad[:5]}"
    )


@skip_if_no_wind
def test_wind_uniform_point_count_per_run_valid_pair(wind: list[WindForecast]) -> None:
    """Every (run_at, valid_at) pair must have the same number of grid points."""
    counts: Counter[tuple] = Counter(
        (w.run_at, w.valid_at) for w in wind
    )
    distinct_counts = set(counts.values())
    assert len(distinct_counts) == 1, (
        f"Unequal point counts per (run_at, valid_at) pair: "
        f"found counts {sorted(distinct_counts)}"
    )


@skip_if_no_wind
def test_wind_inside_study_box(wind: list[WindForecast]) -> None:
    bad = [
        i
        for i, w in enumerate(wind)
        if not (_S <= w.lat <= _N and _W <= w.lon <= _E)
    ]
    assert not bad, f"Wind rows outside study box at indices: {bad[:5]}"


@skip_if_no_wind
def test_wind_dir_from_deg_in_range(wind: list[WindForecast]) -> None:
    bad = [i for i, w in enumerate(wind) if not (0 <= w.dir_from_deg < 360)]
    assert not bad, f"Wind rows with dir_from_deg outside [0, 360) at indices: {bad[:5]}"


@skip_if_no_wind
def test_wind_visible_from_equals_run_at_plus_publish_lag(wind: list[WindForecast]) -> None:
    """Every wind row's visible_from() must equal run_at + HRRR_PUBLISH_LAG_MIN."""
    bad = [
        i
        for i, w in enumerate(wind)
        if w.visible_from() != w.run_at + timedelta(minutes=HRRR_PUBLISH_LAG_MIN)
    ]
    assert not bad, (
        f"Wind rows where visible_from() != run_at + {HRRR_PUBLISH_LAG_MIN} min "
        f"at indices: {bad[:5]}"
    )
