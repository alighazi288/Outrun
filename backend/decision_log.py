"""Append-only log of every plan, help request and human decision, with its time.

Written to data/runs/<run_id>/log.jsonl (gitignored). 
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from backend.clock import as_of
from backend.schemas import Decision


class DecisionLog:
    def __init__(self, path: Path | None = None):
        self.path = path
        self.decisions: list[Decision] = []
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, kind: str, item: BaseModel) -> None:
        if isinstance(item, Decision):
            self.decisions.append(item)
        if self.path is not None:
            entry = {
                "kind": kind,
                "logged_at": datetime.now(UTC).isoformat(),
                "data": json.loads(item.model_dump_json()),
            }
            with self.path.open("a") as f:
                f.write(json.dumps(entry) + "\n")

    def decisions_at(self, t: datetime) -> list[Decision]:
        return as_of(self.decisions, t)
