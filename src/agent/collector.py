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
from agent.metrics import (
    events_collected_total,
    events_deduplicated_total,
    poll_errors_total,
    event_buffer_size,
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
    seen_ids: set = field(default_factory=set)  # For deduplication


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

            if not new_events:
                return []

            deduplicated = 0
            for evt in new_events:
                # Deduplication: generate event ID from timestamp + source + key fields
                evt_id = self._generate_event_id(evt, src)

                if evt_id in src.seen_ids:
                    deduplicated += 1
                    continue

                src.seen_ids.add(evt_id)
                src.events.append(evt)

                # Try multiple timestamp fields the simulator might use
                ts = (
                    evt.get("timestamp")
                    or evt.get("ts")
                    or evt.get("event_time")
                    or evt.get("time")
                    or 0.0
                )
                if ts > src.last_ts:
                    src.last_ts = ts

            # Prune seen_ids to prevent unbounded growth (keep last 1000)
            if len(src.seen_ids) > 1000:
                # Convert to list, keep newest 500
                ids_list = list(src.seen_ids)
                src.seen_ids = set(ids_list[-500:])

            # If no event-level timestamp found, use the response-level one
            # or fall back to current time to advance the cursor
            if src.last_ts == 0.0 or all(
                not evt.get("timestamp") and not evt.get("ts")
                for evt in new_events
            ):
                response_ts = payload.get("timestamp") or payload.get("ts") or 0.0
                if response_ts > src.last_ts:
                    src.last_ts = response_ts
                elif new_events:
                    # Last resort: use current time so we don't re-fetch
                    import time
                    src.last_ts = time.time()

            unique_events = len(new_events) - deduplicated
            src.total_collected += unique_events

            # Update metrics
            if unique_events > 0:
                events_collected_total.labels(
                    use_case=src.use_case, source=src.name
                ).inc(unique_events)
            if deduplicated > 0:
                events_deduplicated_total.labels(
                    use_case=src.use_case, source=src.name
                ).inc(deduplicated)
            event_buffer_size.labels(
                use_case=src.use_case, source=src.name
            ).set(len(src.events))

            if new_events:
                log.debug(
                    "%s/%s: %d new events (%d deduplicated, last_ts=%.3f)",
                    src.use_case, src.name, unique_events, deduplicated, src.last_ts,
                )
            return new_events

        except httpx.HTTPError as e:
            log.warning("Poll failed for %s/%s: %s", src.use_case, src.name, e)
            poll_errors_total.labels(
                use_case=src.use_case, source=src.name
            ).inc()
            return []

    def _generate_event_id(self, evt: dict, src: SourceState) -> str:
        """Generate a unique ID for an event to detect duplicates."""
        # Use event's id field if available
        if "id" in evt:
            return f"{src.use_case}/{src.name}/{evt['id']}"

        # Otherwise, use timestamp + data fingerprint
        data = evt.get("data", evt)
        ts = evt.get("timestamp", evt.get("ts", 0))

        # Create fingerprint from key fields
        fingerprint_parts = [str(ts)]
        for key in sorted(data.keys())[:5]:  # First 5 keys alphabetically
            fingerprint_parts.append(f"{key}:{data[key]}")

        fingerprint = "|".join(fingerprint_parts)
        return f"{src.use_case}/{src.name}/{fingerprint}"

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
