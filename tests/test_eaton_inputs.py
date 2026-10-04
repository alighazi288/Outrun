"""Validate the real Eaton pipeline outputs against schema invariants.

Skipped automatically when the relevant processed file is missing:
- detections tests skip if data/processed/eaton/detections.jsonl is missing
- wind tests skip if data/processed/eaton/wind.jsonl is missing

Run locally after `uv run python scripts/build_detections.py` and
`uv run python scripts/build_wind.py` to verify the processed data.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from backend.schemas import FireDetection, WindForecast
from backend.store import DATASETS, read_jsonl

# ---------------------------------------------------------------------------
# Study bounding box (must match W, S, E, N in build_detections.py /
# build_wind.py)
# ---------------------------------------------------------------------------
_W, _S, _E, _N = -118.23, 34.12, -118.03, 34.26

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
def test_detections_available_at_gte_observed_at(detections: list[FireDetection]) -> None:
    bad = [
        d.id
        for d in detections
        if d.available_at is not None and d.available_at < d.observed_at
    ]
    assert not bad, f"Detections where available_at < observed_at: {bad[:5]}"


@skip_if_no_detections
def test_detections_inside_study_box(detections: list[FireDetection]) -> None:
    bad = [
        d.id
        for d in detections
        if not (_S <= d.lat <= _N and _W <= d.lon <= _E)
    ]
    assert not bad, f"Detections outside study box: {bad[:5]}"


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
def test_wind_times_have_tz_offset(wind: list[WindForecast]) -> None:
    bad_issued = [i for i, w in enumerate(wind) if not _has_tz(w.issued_at)]
    bad_valid = [i for i, w in enumerate(wind) if not _has_tz(w.valid_at)]
    assert not bad_issued, f"Wind rows with naive issued_at at indices: {bad_issued[:5]}"
    assert not bad_valid, f"Wind rows with naive valid_at at indices: {bad_valid[:5]}"


@skip_if_no_wind
def test_wind_issued_at_before_valid_at_plus_4h(wind: list[WindForecast]) -> None:
    """issued_at must be before valid_at + 4 hours.

    HRRR fxx=0 forecasts are for the cycle time itself; with a 60-minute
    publish lag the issued time is 1 hour *after* valid_at, which is fine.
    The 4-hour window is generous enough to cover all fxx 0–3 cases while
    still catching obviously wrong timestamps.
    """
    four_hours = timedelta(hours=4)
    bad = [
        i
        for i, w in enumerate(wind)
        if w.issued_at >= w.valid_at + four_hours
    ]
    assert not bad, (
        f"Wind rows where issued_at >= valid_at + 4h at indices: {bad[:5]}\n"
        f"  example: issued={wind[bad[0]].issued_at}, valid={wind[bad[0]].valid_at}"
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
