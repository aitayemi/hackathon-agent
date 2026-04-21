"""
Real-time web dashboard — serves a live UI over WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent.collector import EventCollector
from agent.analyzer import Analyzer

log = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


def create_app(collector: EventCollector, analyzer: Analyzer) -> FastAPI:
    app = FastAPI(title="Hackathon Agent Dashboard")

    # ── Static files ─────────────────────────────────────────────────────
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    # ── REST snapshot ────────────────────────────────────────────────────
    @app.get("/api/status")
    async def status():
        return _build_snapshot(collector, analyzer)

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
