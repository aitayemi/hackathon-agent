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

**UC1 — Supply Chain** has 4 sources:
- supplier-capacity: tracks supplier capacity_pct, quality_yield_pct, workforce events
- logistics: tracks shipment status, delay_hours, port congestion
- geopolitical: tracks export controls, regulatory changes, severity levels
- inventory: tracks units_on_hand, days_of_supply, reorder_point, alert messages

Anomaly indicators for UC1:
- capacity_pct below 50% (critical if below 30%)
- days_of_supply below 5 (critical if below 2)
- delay_hours above 48 (critical if above 100)
- alert field containing "CRITICAL"
- severity field = "critical" or "high"
- event_type = "export-control" or "workforce-reduction"
- Multiple sources showing problems for the same component_type simultaneously

**UC2 — App Store Compliance** has 4 sources:
- submission-queue: app submissions with declared_capabilities
- policy-kb: policy rule lookups triggered by specific apps
- submission-history: past review outcomes (rejected, warned, approved)
- escalation-queue: escalated reviews with reasons and confidence scores

Anomaly indicators for UC2:
- Same bundle_id appearing repeatedly across multiple sources
- submission-history showing "rejected" or "warned" outcomes
- escalation_queue entries with low reviewer_confidence
- policy-kb lookups triggered by the same app across multiple jurisdictions
- Pattern of the same developer_account having repeated violations

For each analysis cycle, examine ALL the events and report:
1. **Status**: NORMAL or ANOMALY_DETECTED (for each UC independently)
2. **Confidence**: 0.0 to 1.0
3. **Evidence**: Specific data points from the events (include actual numbers)
4. **Recommended Action**: What an operations team should do

Respond ONLY with JSON in this exact structure, no other text:
{
  "timestamp": "ISO-8601",
  "uc1": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."},
  "uc2": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."}
}
"""


def _is_high_priority(evt: dict) -> bool:
    """Check if an event has anomaly indicators based on actual simulator fields."""
    # UC1 supplier-capacity: low capacity
    cap = evt.get("capacity_pct")
    if cap is not None and cap < 50:
        return True

    # UC1 inventory: low days of supply or CRITICAL alert
    dos = evt.get("days_of_supply")
    if dos is not None and dos < 5:
        return True
    alert = evt.get("alert")
    if alert and "CRITICAL" in str(alert).upper():
        return True

    # UC1 logistics: high delays
    delay = evt.get("delay_hours")
    if delay is not None and delay > 48:
        return True

    # UC1 geopolitical: critical/high severity
    sev = str(evt.get("severity", "")).lower()
    if sev in ("critical", "high"):
        return True

    # UC1 geopolitical: export controls
    etype = str(evt.get("event_type", "")).lower()
    if etype in ("export-control", "workforce-reduction"):
        return True

    # UC2 escalation-queue: any escalation
    if evt.get("escalation_reason"):
        return True

    # UC2 submission-history: rejected or warned
    outcome = str(evt.get("outcome", "")).lower()
    if outcome in ("rejected", "warned"):
        return True

    # UC2: known bad actor
    if evt.get("bundle_id") == "com.obscure.tracker":
        return True
    if evt.get("developer_account") == "dev_account_7741":
        return True

    return False


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
            recent = list(src.events)[-50:]
            if not recent:
                sections.append(f"### {src.use_case}/{src.name}: No events yet")
                continue

            sections.append(
                f"### {src.use_case}/{src.name} "
                f"({len(recent)} recent, {src.total_collected} total collected)"
            )

            # Separate high-priority from normal
            high = [e for e in recent if _is_high_priority(e)]
            normal = [e for e in recent if not _is_high_priority(e)]

            # Always include ALL high-priority events, pad with normal
            remaining_slots = max(0, 25 - len(high))
            to_send = high + normal[-remaining_slots:] if remaining_slots else high

            if high:
                sections.append(f"  ⚠ {len(high)} HIGH-PRIORITY events detected:")
            for evt in to_send:
                sections.append(f"  {json.dumps(evt, default=str)}")

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

            # Extract JSON — try multiple strategies
            if "```json" in text:
                text = text.split("```json", 1)[1].rsplit("```", 1)[0]
            elif "```" in text:
                text = text.split("```", 1)[1].rsplit("```", 1)[0]

            try:
                return json.loads(text.strip())
            except json.JSONDecodeError:
                pass

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
        await asyncio.sleep(min(ANALYSIS_INTERVAL, 15))

        while self._running:
            total_events = sum(len(s.events) for s in self.collector.sources)
            if total_events == 0:
                log.info("No events collected yet, skipping analysis")
                await asyncio.sleep(ANALYSIS_INTERVAL)
                continue

            # Count high-priority events across all sources
            hp_count = sum(
                1 for s in self.collector.sources
                for e in list(s.events)[-50:]
                if _is_high_priority(e)
            )

            log.info(
                "Running analysis cycle %d (%d buffered events, %d high-priority)...",
                self.analysis_count + 1, total_events, hp_count,
            )

            summary = self._build_event_summary()
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(
                    None, self._invoke_bedrock, summary
                )
            except Exception as e:
                self._consecutive_failures += 1
                log.warning(
                    "Analysis cycle %d failed (%d consecutive): %s: %s",
                    self.analysis_count + 1, self._consecutive_failures,
                    type(e).__name__, e,
                )
                result = None
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
                log.warning(
                    "Analysis cycle %d produced no result",
                    self.analysis_count + 1,
                )

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
