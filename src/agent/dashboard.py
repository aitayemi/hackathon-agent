"""
Real-time web dashboard — serves a live UI over WebSocket.
Includes API endpoints for injecting events and triggering analysis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from agent.collector import EventCollector
from agent.analyzer import Analyzer

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


# ── Request models ───────────────────────────────────────────────────────
class InjectEvent(BaseModel):
    source: str = Field(
        ...,
        description="Source key, e.g. 'UC1/supplier-capacity' or 'UC2/submission-queue'",
    )
    data: dict[str, Any] = Field(..., description="Event payload")
    timestamp: float | None = Field(
        None, description="Unix timestamp (defaults to now)"
    )


class InjectBatch(BaseModel):
    events: list[InjectEvent]


class AnalyzeResponse(BaseModel):
    cycle: int
    result: dict[str, Any] | None


def create_app(collector: EventCollector, analyzer: Analyzer) -> FastAPI:
    app = FastAPI(title="Hackathon Agent Dashboard")

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    # ── REST snapshot ────────────────────────────────────────────────────
    @app.get("/api/status")
    async def status():
        return _build_snapshot(collector, analyzer)

    # ── Inject events ────────────────────────────────────────────────────
    def _find_source(key: str):
        """Resolve 'UC1/supplier-capacity' to the matching SourceState."""
        for src in collector.sources:
            if f"{src.use_case}/{src.name}" == key:
                return src
        return None

    @app.post("/api/events", summary="Inject one or more events into the collector")
    async def inject_events(batch: InjectBatch):
        injected = 0
        errors = []
        for item in batch.events:
            src = _find_source(item.source)
            if not src:
                errors.append(f"Unknown source: {item.source}")
                continue
            evt = {
                "timestamp": item.timestamp or time.time(),
                "data": item.data,
            }
            src.events.append(evt)
            src.total_collected += 1
            injected += 1

        return {
            "injected": injected,
            "errors": errors,
            "sources": [
                f"{s.use_case}/{s.name}" for s in collector.sources
            ],
        }

    # ── Trigger analysis now ─────────────────────────────────────────────
    @app.post("/api/analyze", summary="Trigger an immediate Bedrock analysis cycle")
    async def trigger_analysis():
        total_events = sum(len(s.events) for s in collector.sources)
        if total_events == 0:
            raise HTTPException(
                status_code=400,
                detail="No events in buffer. Inject events first via POST /api/events",
            )

        log.info("API-triggered analysis cycle (%d buffered events)", total_events)
        summary = analyzer._build_event_summary()
        loop = asyncio.get_event_loop()

        try:
            result = await loop.run_in_executor(None, analyzer._invoke_bedrock, summary)
        except Exception as e:
            raise HTTPException(
                status_code=502,
                detail=f"Bedrock invocation exception: {type(e).__name__}: {e}",
            )

        if result:
            analyzer.last_result = result
            analyzer.analysis_count += 1
            analyzer._log_result(result)
            return {"cycle": analyzer.analysis_count, "result": result}
        else:
            raise HTTPException(
                status_code=502,
                detail=f"Bedrock invocation returned no result — check agent logs for details",
            )

    # ── WebSocket for live updates ───────────────────────────────────────
    connected: set[WebSocket] = set()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        connected.add(ws)
        log.info("Dashboard client connected (%d total)", len(connected))
        try:
            # Send initial snapshot immediately
            await ws.send_text(json.dumps(_build_snapshot(collector, analyzer), default=str))
            # Then keep pushing updates
            while True:
                await asyncio.sleep(2)
                payload = _build_snapshot(collector, analyzer)
                await ws.send_text(json.dumps(payload, default=str))
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.debug("WebSocket error: %s", e)
        finally:
            connected.discard(ws)
            log.info("Dashboard client disconnected (%d remaining)", len(connected))

    # ── Static files (MUST be last — mounted apps are greedy) ────────────
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


def _build_snapshot(collector: EventCollector, analyzer: Analyzer) -> dict:
    """Build a JSON-serializable snapshot of the agent's current state."""
    now = datetime.now(timezone.utc).isoformat()

    sources = []
    for src in collector.sources:
        recent_events = []
        for evt in list(src.events)[-20:]:  # last 20 per source
            recent_events.append({
                "timestamp": evt.get("timestamp", 0),
                "data": evt.get("data", {}),
            })

        sources.append({
            "use_case": src.use_case,
            "name": src.name,
            "total_collected": src.total_collected,
            "buffered": len(src.events),
            "recent_events": recent_events,
        })

    # Aggregate per use-case
    uc1_total = sum(s["total_collected"] for s in sources if s["use_case"] == "UC1")
    uc2_total = sum(s["total_collected"] for s in sources if s["use_case"] == "UC2")
    uc1_buffered = sum(s["buffered"] for s in sources if s["use_case"] == "UC1")
    uc2_buffered = sum(s["buffered"] for s in sources if s["use_case"] == "UC2")

    # Analysis result
    analysis = None
    if analyzer.last_result:
        analysis = analyzer.last_result

    return {
        "timestamp": now,
        "agent": {
            "uptime_sources": len(collector.sources),
            "analysis_count": analyzer.analysis_count,
        },
        "collection": {
            "uc1": {"total": uc1_total, "buffered": uc1_buffered},
            "uc2": {"total": uc2_total, "buffered": uc2_buffered},
        },
        "sources": sources,
        "analysis": analysis,
    }
