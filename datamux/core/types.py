"""Core data types for datamux."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

DataType = Literal["news", "tick", "bar", "position", "prediction", "capital_flow", "vessel", "sanction", "document", "poll"]
TargetDB = Literal["news", "market"]

# Map data types to their target database
DATA_TYPE_TO_DB: dict[DataType, TargetDB] = {
    "news": "news",
    "tick": "market",
    "bar": "market",
    "position": "market",
    "prediction": "market",
    "capital_flow": "market",
    "vessel": "market",
    "sanction": "market",
    "document": "news",
    "poll": "market",
}


def utcnow_iso() -> str:
    """Return current UTC time as ISO8601 string with Z suffix."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class FetchResult:
    """Result of a source fetch operation."""

    source: str
    data_type: DataType
    items: list[dict[str, Any]]
    fetched_at: str = field(default_factory=utcnow_iso)
    cursor: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass
class WriteOp:
    """A write operation to be consumed by the DBWriter."""

    source: str
    data_type: DataType
    items: list[dict[str, Any]]
    cursor: dict[str, Any] | None = None

    @property
    def target_db(self) -> TargetDB:
        return DATA_TYPE_TO_DB[self.data_type]

    @property
    def count(self) -> int:
        return len(self.items)


@dataclass
class SourceHealth:
    """Health status for a single source."""

    source: str
    last_success_at: str | None = None
    last_error: str | None = None
    last_error_at: str | None = None
    consecutive_errors: int = 0
    total_fetches: int = 0
    total_errors: int = 0
    last_fetch_duration_ms: int | None = None
    is_circuit_open: bool = False
