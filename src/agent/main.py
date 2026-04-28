"""
Entry point — runs the collector, analyzer, and web dashboard concurrently.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys

import uvicorn
import structlog

from agent.collector import EventCollector
from agent.analyzer import Analyzer
from agent.dashboard import create_app
from agent.config import config
from agent.metrics import agent_info

log = structlog.get_logger("agent")


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

    # Set agent info for Prometheus
    agent_info.info({
        "uc1_endpoint": config.uc1_base_url,
        "uc2_endpoint": config.uc2_base_url,
        "bedrock_model": config.bedrock_model_id,
        "bedrock_region": config.bedrock_region,
    })

    log.info(
        "agent_starting",
        uc1_endpoint=config.uc1_base_url,
        uc2_endpoint=config.uc2_base_url,
        poll_interval=config.poll_interval,
        analysis_interval=config.analysis_interval,
        dashboard_port=config.dashboard_port,
        bedrock_model=config.bedrock_model_id,
        bedrock_fallback=config.bedrock_fallback_model_id,
    )

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()
    for sig_ in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig_, lambda: _shutdown(collector, analyzer))

    # Start the dashboard web server
    app = create_app(collector, analyzer)
    uvicorn_config = uvicorn.Config(
        app, host="0.0.0.0", port=config.dashboard_port,
        log_level="warning",  # keep console clean
    )
    server = uvicorn.Server(uvicorn_config)

    await asyncio.gather(
        collector.run(),
        analyzer.run(),
        server.serve(),
        _status_printer(collector, analyzer),
    )


def _shutdown(collector: EventCollector, analyzer: Analyzer):
    log.info("agent_shutting_down")
    collector.stop()
    analyzer.stop()


def _setup_logging():
    """Configure structured logging with both human-readable and JSON output."""
    # Check if running in K8s (look for SERVICE_ACCOUNT env var)
    import os
    is_k8s = os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount")

    if is_k8s or os.getenv("LOG_FORMAT") == "json":
        # JSON logging for production/K8s
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )
    else:
        # Human-readable console logging for local dev
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
    )


def main():
    _setup_logging()
    asyncio.run(run())


if __name__ == "__main__":
    main()
