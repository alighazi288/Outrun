"""No hindsight: nothing observed, issued or reported after t is ever visible at t."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.clock import ReplayClock, as_of
from backend.schemas import FireDetection

from .conftest import pt


def det(observed: datetime, available: datetime | None = None) -> FireDetection:
    """Published at `available`, or the moment it was observed (publish delays have their own
    tests in test_contract.py)."""
    return FireDetection(id="d", lat=34.19, lon=-118.1, h3="x", observed_at=observed,
                         available_at=available or observed)


def test_as_of_boundary():
    t = pt("22:00")
    assert as_of([det(t)], t), "a record at exactly t is visible"
    assert not as_of([det(t + timedelta(seconds=1))], t), "a record at t+1s is not"


def test_detection_hidden_until_published():
    observed, published = pt("22:00"), pt("22:45")
    d = det(observed, published)
    assert not as_of([d], pt("22:30"))
    assert as_of([d], pt("22:45"))


def test_naive_time_rejected():
    with pytest.raises(ValueError):
        as_of([], datetime(2025, 1, 7, 22, 0))


def test_other_timezones_compare_correctly():
    same_instant_in_utc = pt("22:00").astimezone(UTC)
    assert as_of([det(pt("22:00"))], same_instant_in_utc)


def test_store_never_leaks_future_records(store):
    """Property check over the whole replay: every visible record existed by t."""
    for t in store.make_clock().times():
        snap = store.at(t)
        for group in (snap.detections, snap.reports, snap.wind, snap.orders, snap.residents):
            for r in group:
                seen = r.visible_from()
                assert seen is None or seen <= t


def test_clock_steps_and_clamps():
    c = ReplayClock(start=pt("18:00"), end=pt("19:00"), step=timedelta(minutes=10))
    assert len(c.times()) == 7
    assert c.advance() == pt("18:10")
    assert c.advance(100) == pt("19:00")
    assert c.reset() == pt("18:00")
