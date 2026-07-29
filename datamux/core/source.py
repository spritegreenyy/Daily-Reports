"""Base classes for data sources."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from datamux.core.types import DataType, FetchResult, WriteOp

logger = logging.getLogger(__name__)


class BasePollingSource(ABC):
    """Base class for polling data sources (REST APIs, RSS feeds, etc.)."""

    name: str
    data_type: DataType

    @abstractmethod
    async def fetch(self, cursor: dict[str, Any] | None) -> FetchResult:
        """Fetch data from the source.

        Args:
            cursor: Previous cursor for incremental fetching, or None for first run.

        Returns:
            FetchResult containing normalized items and next cursor.
        """

    @abstractmethod
    def normalize(self, raw: Any) -> list[dict[str, Any]]:
        """Normalize raw data into a list of dicts ready for DB insertion.

        Each dict should match the target table schema.
        """

    async def ping(self) -> dict[str, Any]:
        """Optional health check. Override to provide source-specific checks."""
        return {"status": "ok", "source": self.name}

    def to_write_op(self, result: FetchResult) -> WriteOp:
        """Convert a FetchResult into a WriteOp for the write queue."""
        return WriteOp(
            source=result.source,
            data_type=result.data_type,
            items=result.items,
            cursor=result.cursor,
        )


class SyncSourceMixin:
    """Mixin for sources that use synchronous libraries (fundus, feedparser, rqdatac).

    Implement _fetch_sync() instead of fetch(). The mixin wraps it in
    asyncio.to_thread() so it runs without blocking the event loop.
    """

    @abstractmethod
    def _fetch_sync(self, cursor: dict[str, Any] | None) -> FetchResult:
        """Synchronous fetch implementation. Runs in a thread."""

    async def fetch(self, cursor: dict[str, Any] | None) -> FetchResult:
        return await asyncio.to_thread(self._fetch_sync, cursor)


class BaseStreamSource(ABC):
    """Base class for streaming data sources (WebSocket, long-polling)."""

    name: str
    data_type: DataType
    reconnect_base_delay: float = 2.0
    reconnect_max_delay: float = 60.0

    @abstractmethod
    async def connect(self) -> Any:
        """Establish connection. Returns a connection object."""

    @abstractmethod
    async def subscribe(self, conn: Any):
        """Send subscription messages after connecting."""

    @abstractmethod
    async def on_message(self, raw: Any) -> list[WriteOp]:
        """Process an incoming message.

        Returns a list of WriteOps to be queued (may be empty for
        heartbeats or irrelevant messages).
        """

    async def on_disconnect(self, exc: Exception | None):
        """Called when connection drops. Override for custom cleanup."""
        if exc:
            logger.warning("%s disconnected: %s", self.name, exc)

    async def on_connect(self):
        """Called after successful connection + subscription."""
        logger.info("%s connected", self.name)


class BlockingStreamSource(ABC):
    """Base class for blocking stream sources (e.g. RQData LiveMarketDataClient).

    These run in a separate thread via ThreadBridge, not on the asyncio loop.
    Implement listen() as a blocking iterator and on_data() to normalize.
    """

    name: str
    data_type: DataType

    @abstractmethod
    def listen(self):
        """Blocking iterator that yields raw data items.

        This runs in a dedicated thread managed by ThreadBridge.
        """

    @abstractmethod
    def on_data(self, raw: Any) -> WriteOp:
        """Normalize a single raw data item into a WriteOp."""

    def stop(self):
        """Optional: signal the listener to stop. Override if needed."""
