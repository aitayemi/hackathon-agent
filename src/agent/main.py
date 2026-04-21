"""
Entry point — runs the collector, analyzer, and web dashboard concurrently.
"""
from __future__ import annotations

import asyncio
import logging
import signal

import uvicorn
from rich.logging import RichHandler

from agent.collector import EventCollector
from agent.analyzer import Analyzer
from agent.dashboard import create_app
from agent.config import (
    UC1_BASE_URL, UC2_BASE_URL, POLL_INTERVAL, ANALYSIS_INTERVAL,
    DASHBOARD_PORT,
)

log = logging.getLogger("agent")


async def _status_printer(collector: EventCollector, analyzer: Analyzer):
    """Periodically prints a status summary to the log."""
    while True:
        await asyncio.sleep(15)
        lines = []
        for src in collector.sources:
            lines.append(f"  {src.use_case}/{src.name}: {src.total_collected} total, {len(src.events)} buffered")
        log.info(
            "Status — %d sources, %d analyses completed\n%s",
            len(collector.sources),
            analyzer.analysis_count,
            "\n".join(lines),
        )


async def run():
    collector = EventCollector()
    analyzer = Analyzer(collector)

    log.info("Hackathon Agent starting")
    log.info("  UC1 endpoint: %s", UC1_BASE_URL)
    log.info("  UC2 endpoint: %s", UC2_BASE_URL)
    log.info("  Poll interval: %.1fs", POLL_INTERVAL)
    log.info("  Analysis interval: %.0fs", ANALYSIS_INTERVAL)
    log.info("  Dashboard: http://localhost:%d", DASHBOARD_PORT)

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    for sig_ in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_, lambda: _shutdown(collector, analyzer))

    # Start the dashboard web server
    app = create_app(collector, analyzer)
    config = uvicorn.Config(
        app, host="0.0.0.0", port=DASHBOARD_PORT,
        log_level="warning",  # keep console clean
    )
    server = uvicorn.Server(config)

    await asyncio.gather(
        collector.run(),
        analyzer.run(),
        server.serve(),
        _status_printer(collector, analyzer),
    )


def _shutdown(collector: EventCollector, analyzer: Analyzer):
    log.info("Shutting down...")
    collector.stop()
    analyzer.stop()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
