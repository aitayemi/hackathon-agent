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
logistics, geopolitical, and inventory. Look for anomalies such as:
- Sudden capacity drops from key suppliers (especially APAC-East region)
- Export restrictions or policy changes affecting component supply
- Logistics congestion, route suspensions, or unusual shipping delays
- Inventory levels falling below safety stock thresholds
- Cascading patterns where a supplier issue triggers logistics and inventory problems
- Any event with severity CRITICAL or HIGH
- Rapid changes in metrics (capacity %, stock levels, delay hours)

**UC2 — App Store Compliance:** You receive events from 4 sources: \
submission-queue, policy-kb, submission-history, and escalation-queue. Look for:
- Privacy manifest discrepancies (declared vs detected data types)
- Undisclosed tracking SDKs or data collection capabilities
- Progressive obfuscation patterns across app versions
- Policy violations flagged by automated scanning
- Auto-escalations due to repeated violations
- High risk scores from binary analysis
- Any developer account with multiple warnings

IMPORTANT: Analyze ALL events provided. If you see events with severity \
"CRITICAL" or "HIGH", or metrics that indicate problems (low capacity, \
low inventory, policy violations, high risk scores), you SHOULD flag them \
as ANOMALY_DETECTED with appropriate confidence.

For each analysis cycle, examine the recent events and report:
1. **Status**: NORMAL or ANOMALY_DETECTED (for each UC independently)
2. **Confidence**: 0.0 to 1.0
3. **Evidence**: Specific events or patterns that support your assessment
4. **Recommended Action**: What an operations team should do

Respond ONLY with JSON in this exact structure, no other text:
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
        self._consecutive_failures = 0

    def _build_event_summary(self) -> str:
        """Build a text summary of recent events for the LLM."""
        sections = []
        for src in self.collector.sources:
            recent = list(src.events)[-50:]  # last 50 events per source
            if not recent:
                sections.append(f"### {src.use_case}/{src.name}: No events yet")
                continue

            sections.append(f"### {src.use_case}/{src.name} ({len(recent)} recent events, {src.total_collected} total)")

            # Prioritize events with severity or anomaly indicators
            high_priority = []
            normal = []
            for evt in recent:
                data = evt.get("data", {})
                severity = str(data.get("severity", "")).upper()
                if severity in ("CRITICAL", "HIGH") or data.get("risk_score", 0) > 0.7:
                    high_priority.append(evt)
                else:
                    normal.append(evt)

            # Send all high-priority events, then fill remaining with normal
            to_send = high_priority + normal[-max(0, 20 - len(high_priority)):]

            for evt in to_send:
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
                            f"{event_summary}"
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
        # Short initial wait to let some events accumulate
        await asyncio.sleep(min(ANALYSIS_INTERVAL, 15))

        while self._running:
            total_events = sum(len(s.events) for s in self.collector.sources)
            if total_events == 0:
                log.info("No events collected yet, skipping analysis")
                await asyncio.sleep(ANALYSIS_INTERVAL)
                continue

            log.info("Running analysis cycle %d (%d buffered events)...",
                     self.analysis_count + 1, total_events)

            summary = self._build_event_summary()
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, self._invoke_bedrock, summary)
            except Exception as e:
                self._consecutive_failures += 1
                log.warning("Analysis cycle %d failed (%d consecutive): %s: %s",
                            self.analysis_count + 1, self._consecutive_failures,
                            type(e).__name__, e)
                result = None
                # Back off if we keep failing
                if self._consecutive_failures >= 3:
                    backoff = min(ANALYSIS_INTERVAL * 2, 120)
                    log.warning("Multiple failures — backing off %.0fs", backoff)
                    await asyncio.sleep(backoff)
                    continue

            if result:
                self._consecutive_failures = 0
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
