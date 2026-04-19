"""
Event collector — polls simulator endpoints and buffers events in memory.
"""
from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass, field

import httpx

from agent.config import (
    UC1_BASE_URL, UC2_BASE_URL,
    UC1_SOURCES, UC2_SOURCES,
    POLL_INTERVAL, EVENT_WINDOW_SIZE,
)

log = logging.getLogger(__name__)


@dataclass
class SourceState:
    """Tracks polling state for one signal source."""
    use_case: str
    name: str
    base_url: str
    last_ts: float = 0.0
    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_WINDOW_SIZE))
    total_collected: int = 0


class EventCollector:
    """Polls all simulator sources and stores events in a rolling buffer."""

    def __init__(self):
        self.sources: list[SourceState] = []
        for name in UC1_SOURCES:
            self.sources.append(SourceState(use_case="UC1", name=name, base_url=UC1_BASE_URL))
        for name in UC2_SOURCES:
            self.sources.append(SourceState(use_case="UC2", name=name, base_url=UC2_BASE_URL))

        self._client = httpx.AsyncClient(timeout=10.0)
        self._running = False

    async def poll_source(self, src: SourceState) -> list[dict]:
        """Poll one source for new events since last timestamp."""
        url = f"{src.base_url}/{src.name}/events"
        params = {"since": src.last_ts, "limit": 200}
        try:
            resp = await self._client.get(url, params=params)
            resp.raise_for_status()
            payload = resp.json()
            new_events = payload.get("events", [])

            for evt in new_events:
                src.events.append(evt)
                ts = evt.get("timestamp", 0.0)
                if ts > src.last_ts:
                    src.last_ts = ts
            src.total_collected += len(new_events)
            return new_events

        except httpx.HTTPError as e:
            log.warning("Poll failed for %s/%s: %s", src.use_case, src.name, e)
            return []

    async def poll_all(self) -> dict[str, list[dict]]:
        """Poll all sources concurrently. Returns {source_key: [new_events]}."""
        tasks = {f"{s.use_case}/{s.name}": self.poll_source(s) for s in self.sources}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        return {
            key: (r if isinstance(r, list) else [])
            for key, r in zip(tasks.keys(), results)
        }

    async def run(self):
        """Continuous polling loop."""
        self._running = True
        log.info("Collector started — polling %d sources every %.1fs", len(self.sources), POLL_INTERVAL)
        while self._running:
            await self.poll_all()
            await asyncio.sleep(POLL_INTERVAL)

    def stop(self):
        self._running = False
