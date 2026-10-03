from __future__ import annotations

import pytest

from backend.clock import parse_t
from backend.store import DATASETS, DataStore


@pytest.fixture
def store() -> DataStore:
    """A fresh copy of the fake fixture dataset for each test."""
    return DataStore(DATASETS["fixtures"])


def pt(hhmm: str, day: int = 7) -> object:
    """Pacific time on the fire night: pt("21:30") -> 2025-01-07T21:30-08:00."""
    return parse_t(f"2025-01-{day:02d}T{hhmm}:00-08:00")
