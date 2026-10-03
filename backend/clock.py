"""Replay clock and the no-hindsight filter.

`as_of()` is the single place where "only use what existed at time t" is enforced.
Every data read in the backend goes through `DataStore.at(t)`, which calls `as_of()`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol, TypeVar
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


class HasVisibility(Protocol):
    def visible_from(self) -> datetime | None: ...


T = TypeVar("T", bound=HasVisibility)


def require_aware(t: datetime) -> datetime:
    """Reject naive datetimes: comparing naive and aware times silently breaks the filter."""
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError(f"time must be timezone-aware (got naive {t!r})")
    return t


def parse_t(value: str) -> datetime:
    """Parse an ISO-8601 time string that includes a UTC offset."""
    return require_aware(datetime.fromisoformat(value))


def as_of(records: Iterable[T], t: datetime) -> list[T]:
    """Keep only records that existed at or before t. Records with no timestamp are kept
    (they were known before the fire, e.g. the road network or the resident registry)."""
    require_aware(t)
    out = []
    for r in records:
        seen = r.visible_from()
        if seen is None or seen <= t:
            out.append(r)
    return out


@dataclass
class ReplayClock:
    """Steps through a past event at a fixed interval."""

    start: datetime
    end: datetime
    step: timedelta
    now: datetime = field(init=False)

    def __post_init__(self) -> None:
        require_aware(self.start)
        require_aware(self.end)
        if self.end < self.start:
            raise ValueError("end must be after start")
        self.now = self.start

    def advance(self, n: int = 1) -> datetime:
        """Move forward n steps (clamped to the end of the replay)."""
        self.now = min(self.now + n * self.step, self.end)
        return self.now

    def reset(self) -> datetime:
        self.now = self.start
        return self.now

    def times(self) -> list[datetime]:
        """Every step time from start to end, inclusive."""
        out, t = [], self.start
        while t <= self.end:
            out.append(t)
            t += self.step
        return out
