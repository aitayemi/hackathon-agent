"""
Anomaly analyzer — periodically sends buffered events to Bedrock for analysis.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone

import boto3

from agent.collector import EventCollector
from agent.config import BEDROCK_REGION, BEDROCK_MODEL_ID, ANALYSIS_INTERVAL
from agent.notifier import send_analysis_email

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an anomaly detection agent monitoring two live data streams from a \
tech company's operations platform. You MUST analyze every event carefully.

**UC1 — Supply Chain** (4 sources: supplier-capacity, logistics, geopolitical, inventory):

Anomaly indicators to watch for:
- supplier-capacity: capacity_pct below 50% is concerning, below 30% is critical. \
  Watch for event_types like "workforce-reduction", "quality-hold", "planned-downtime" \
  especially from tier-1 suppliers. Low quality_yield_pct (below 85%) compounds the problem.
- logistics: delay_hours above 48 is concerning, above 100 is critical. \
  Watch for status "delayed" with delay_cause "port-congestion" or "export-hold". \
  Multiple delayed shipments for the same component_type indicates a systemic issue.
- inventory: days_of_supply below 5 is concerning, below 2 is critical. \
  units_on_hand far below reorder_point with in_transit_units at 0 is an emergency. \
  The "alert" field containing "CRITICAL" is an explicit alarm.
- geopolitical: severity "critical" or "high" events, especially "export-control" \
  event_types affecting component supply chains.

The cascading pattern: A supplier capacity collapse → logistics delays → inventory \
depletion is the highest-severity anomaly. If you see CoreFab International with \
low capacity AND cellular-modem logistics delays AND cellular-modem inventory \
alerts, that is a confirmed cascading supply chain disruption.

**UC2 — App Store Compliance** (4 sources: submission-queue, policy-kb, \
submission-history, escalation-queue):

Anomaly indicators to watch for:
- submission-queue: Repeated submissions from the same bundle_id/developer_account \
  with suspicious declared_capabilities. Watch for com.obscure.tracker / dev_account_7741.
- policy-kb: High-confidence rule lookups triggered by the same app, especially \
  section "5.1.1 Data Collection and Storage".
- submission-history: Past rejections for the same developer, especially for \
  privacy violations. remediation_taken: false or repeated violations is a red flag.
- escalation-queue: Any escalation with reason mentioning "prior violation pattern" \
  or "underdeclaration". Low reviewer_confidence with serious policy citations.

The progressive obfuscation pattern: A developer repeatedly submitting an app that \
triggers privacy policy lookups, has past rejections for data collection violations, \
and gets escalated for "prior violation pattern" is the key anomaly.

IMPORTANT RULES:
1. If you see events matching these patterns, you MUST report ANOMALY_DETECTED.
2. If the previous analysis already detected an anomaly and the underlying conditions \
   have NOT improved (capacity still low, delays still high, inventory still critical, \
   app still being flagged), you MUST continue reporting ANOMALY_DETECTED. Anomalies \
   do not resolve until the metrics return to normal ranges.
3. Your confidence should INCREASE over time if the anomaly persists or worsens.
4. Include specific numbers from the events in your evidence (e.g., "capacity_pct: 29%").

Respond ONLY with JSON in this exact structure, no other text:
{
  "timestamp": "ISO-8601",
  "uc1": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."},
  "uc2": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."}
}
"""


def _is_high_priority(evt: dict) -> bool:
    """Check if an event has anomaly-relevant signals based on actual simulator fields."""
    data = evt.get("data", evt)

    cap = data.get("capacity_pct")
    if cap is not None and cap < 50:
        return True

    dos = data.get("days_of_supply")
    if dos is not None and dos < 5:
        return True
    alert = str(data.get("alert") or "")
    if "CRITICAL" in alert:
        return True

    delay = data.get("delay_hours")
    if delay is not None and delay > 48:
        return True

    sev = str(data.get("severity", "")).lower()
    if sev in ("critical", "high"):
        return True

    if data.get("escalation_reason"):
        return True
    if data.get("outcome") == "rejected":
        return True
    if data.get("bundle_id") == "com.obscure.tracker":
        return True
    if data.get("triggered_by") == "com.obscure.tracker":
        return True

    return False


class Analyzer:
    """Periodically analyzes buffered events via Bedrock."""

    MAX_HISTORY = 50

    def __init__(self, collector: EventCollector):
        self.collector = collector
        self._client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
        self._running = False
        self.last_result: dict | None = None
        self.result_history: deque[dict] = deque(maxlen=self.MAX_HISTORY)
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
                f"({len(recent)} recent events, {src.total_collected} total collected)"
            )

            high = [e for e in recent if _is_high_priority(e)]
            normal = [e for e in recent if not _is_high_priority(e)]

            remaining_slots = max(0, 25 - len(high))
            to_send = high + normal[-remaining_slots:] if remaining_slots else high

            if high:
                sections.append(f"  ⚠ {len(high)} HIGH-PRIORITY events detected:")
            for evt in to_send:
                data = evt.get("data", evt)
                sections.append(f"  {json.dumps(data, default=str)}")

        return "\n".join(sections)

    def _build_prompt(self, event_summary: str) -> str:
        """Build the full user prompt including previous analysis context."""
        now = datetime.now(timezone.utc).isoformat()
        parts = [f"Analyze these recent events (collected at {now}):\n\n{event_summary}"]

        # Include previous result so the LLM maintains continuity
        if self.last_result:
            parts.append(
                f"\n\n--- PREVIOUS ANALYSIS (cycle #{self.analysis_count}) ---\n"
                f"{json.dumps(self.last_result, default=str)}\n"
                f"--- END PREVIOUS ANALYSIS ---\n\n"
                f"If the anomaly conditions from the previous analysis are still present "
                f"in the current events, you MUST continue reporting ANOMALY_DETECTED "
                f"with equal or higher confidence. Only report NORMAL if the metrics "
                f"have genuinely returned to safe ranges (capacity > 70%, days_of_supply > 10, "
                f"delay_hours < 24, no more escalations for the flagged app)."
            )

        return "\n".join(parts)

    def _invoke_bedrock(self, prompt: str) -> dict | None:
        """Call Bedrock with the prompt and return parsed JSON."""
        try:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 4096,
                "system": SYSTEM_PROMPT,
                "messages": [
                    {"role": "user", "content": prompt},
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

            hp_count = sum(
                1 for s in self.collector.sources
                for e in list(s.events)[-50:]
                if _is_high_priority(e)
            )

            log.info(
                "Running analysis cycle %d (%d buffered events, %d high-priority)...",
                self.analysis_count + 1, total_events, hp_count,
            )

            event_summary = self._build_event_summary()
            prompt = self._build_prompt(event_summary)
            loop = asyncio.get_event_loop()
            try:
                result = await loop.run_in_executor(None, self._invoke_bedrock, prompt)
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
                # Add cycle metadata
                result["cycle"] = self.analysis_count + 1
                result["high_priority_count"] = hp_count
                result["total_events"] = total_events

                self.last_result = result
                self.result_history.append(result)
                self.analysis_count += 1
                self._log_result(result)

                # Send email notification
                await asyncio.get_event_loop().run_in_executor(
                    None, send_analysis_email, result,
                )
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
