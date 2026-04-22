"""
Anomaly analyzer — periodically sends buffered events to Bedrock for analysis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import boto3

from agent.collector import EventCollector
from agent.config import BEDROCK_REGION, BEDROCK_MODEL_ID, ANALYSIS_INTERVAL

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an anomaly detection agent monitoring two live data streams from a \
tech company's operations platform.

**UC1 — Supply Chain:** You receive events from 4 sources: supplier-capacity, \
logistics, geopolitical, and inventory. The anomaly pattern to detect is a \
cascading supply chain disruption: a critical APAC-East supplier (CoreFab \
International) experiencing capacity collapse driven by export restrictions, \
causing logistics congestion and dangerously low inventory for the \
cellular-modem component.

**UC2 — App Store Compliance:** You receive events from 4 sources: \
submission-queue, policy-kb, submission-history, and escalation-queue. The \
anomaly pattern is a developer account (dev_account_7741 / com.obscure.tracker) \
progressively obscuring data collection practices — incomplete privacy \
manifests, misclassified data types, and undisclosed tracking capabilities.

For each analysis cycle, examine the recent events and report:
1. **Status**: NORMAL or ANOMALY_DETECTED (for each UC independently)
2. **Confidence**: 0.0 to 1.0
3. **Evidence**: Specific events or patterns that support your assessment
4. **Recommended Action**: What an operations team should do

Respond in JSON with this structure:
{
  "timestamp": "ISO-8601",
  "uc1": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."},
  "uc2": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."}
}
"""


class Analyzer:
    """Periodically analyzes buffered events via Bedrock."""

    def __init__(self, collector: EventCollector):
        self.collector = collector
        self._client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        self._running = False
        self.last_result: dict | None = None
        self.analysis_count = 0

    def _build_event_summary(self) -> str:
        """Build a text summary of recent events for the LLM."""
        sections = []
        for src in self.collector.sources:
            recent = list(src.events)[-30:]  # last 30 events per source
            if not recent:
                sections.append(f"### {src.use_case}/{src.name}: No events yet")
                continue

            sections.append(f"### {src.use_case}/{src.name} ({len(recent)} recent events)")
            # Send a sample — full events for small counts, summarized for large
            sample = recent[-10:]  # last 10 for the prompt
            for evt in sample:
                data = evt.get("data", {})
                sections.append(f"  {json.dumps(data, default=str)}")

        return "\n".join(sections)

    def _invoke_bedrock(self, event_summary: str) -> dict | None:
        """Call Bedrock with the event summary and return parsed JSON."""
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            f"Analyze these recent events (collected at "
                            f"{datetime.now(timezone.utc).isoformat()}):\n\n"
                            f"{event_summary}\n\n"
                            f"Respond ONLY with the JSON object, no other text."
                        ),
                    }
                ],
            })

            response = self._client.invoke_model(
                modelId=BEDROCK_MODEL_ID,
                contentType="application/json",
                accept="application/json",
                body=body,
            )

            result = json.loads(response["body"].read())
            text = result["content"][0]["text"]
            log.debug("Raw Bedrock response (first 500 chars): %s", text[:500])

            # Extract JSON from the response — try multiple strategies
            # 1. Strip markdown code fences
            if "```json" in text:
                text = text.split("```json", 1)[1].rsplit("```", 1)[0]
            elif "```" in text:
                text = text.split("```", 1)[1].rsplit("```", 1)[0]

            # 2. Try parsing as-is
            try:
                return json.loads(text.strip())
            except json.JSONDecodeError:
                pass

            # 3. Find the first { ... last } and try that
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass

            log.error("Could not parse JSON from Bedrock response: %s", text[:1000])
            raise ValueError(f"Bedrock returned unparseable response: {text[:300]}")

        except Exception as e:
            log.error("Bedrock invocation failed: %s: %s", type(e).__name__, e)
            raise

    async def run(self):
        """Periodic analysis loop."""
        self._running = True
        log.info(
            "Analyzer started — running every %.0fs with model %s",
            ANALYSIS_INTERVAL, BEDROCK_MODEL_ID,
        )
        # Wait for some events to accumulate before first analysis
        await asyncio.sleep(ANALYSIS_INTERVAL)

        while self._running:
            total_events = sum(len(s.events) for s in self.collector.sources)
            if total_events == 0:
                log.info("No events collected yet, skipping analysis")
                await asyncio.sleep(ANALYSIS_INTERVAL)
                continue

            log.info("Running analysis cycle %d (%d buffered events)...",
                     self.analysis_count + 1, total_events)

            summary = self._build_event_summary()
            # Run the synchronous Bedrock call in a thread to avoid blocking
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, self._invoke_bedrock, summary)
            except Exception as e:
                log.warning("Analysis cycle %d failed: %s: %s",
                            self.analysis_count + 1, type(e).__name__, e)
                result = None

            if result:
                self.last_result = result
                self.analysis_count += 1
                self._log_result(result)
            else:
                log.warning("Analysis cycle %d produced no result", self.analysis_count + 1)

            await asyncio.sleep(ANALYSIS_INTERVAL)

    def _log_result(self, result: dict):
        """Pretty-print the analysis result."""
        for uc_key in ["uc1", "uc2"]:
            uc = result.get(uc_key, {})
            status = uc.get("status", "UNKNOWN")
            confidence = uc.get("confidence", 0)
            action = uc.get("action", "N/A")
            evidence = uc.get("evidence", [])

            icon = "🔴" if status == "ANOMALY_DETECTED" else "🟢"
            log.info(
                "%s %s: %s (confidence=%.0f%%) — %s",
                icon, uc_key.upper(), status, confidence * 100, action,
            )
            for e in evidence[:3]:
                log.info("   ↳ %s", e)

    def stop(self):
        self._running = False
