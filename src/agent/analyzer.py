"""
Anomaly analyzer — periodically sends buffered events to Bedrock for analysis.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from datetime import datetime, timezone

import boto3
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from agent.collector import EventCollector
from agent.config import config
from agent.notifier import send_analysis_email
from agent.metrics import (
    analysis_cycles_total,
    analysis_duration_seconds,
    analysis_failures_total,
    anomalies_detected_total,
    anomaly_confidence,
    high_priority_events,
)

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You are an advanced anomaly detection agent with temporal reasoning capabilities, \
monitoring two live data streams from a tech company's operations platform. You have \
access to 6 HOURS of historical analysis context and MUST use temporal trends to \
improve accuracy.

**TEMPORAL ANALYSIS CAPABILITIES:**
You will receive multi-window trend analysis (10min, 30min, 1hour, 3hour, 6hour) showing:
- Anomaly rates over time
- Confidence trends (rising/falling/stable)
- Historical patterns and persistence

Use this temporal context to:
1. Detect rate-of-change anomalies (rapid deterioration)
2. Avoid false negatives from persistent issues
3. Prevent premature "all clear" signals
4. Identify improving vs. worsening situations

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

CRITICAL RULES FOR TEMPORAL REASONING:
1. **Persistence Check**: If anomaly_rate over 6-hour window > 50%, this is a PERSISTENT \
   issue. You MUST continue reporting ANOMALY_DETECTED with confidence ≥ previous.

2. **Escalation Detection**: If anomaly_rate in 10min > 30min > 1hour, the situation is \
   WORSENING. Increase confidence by 0.1-0.2 and emphasize urgency in action.

3. **De-escalation Criteria**: Only report NORMAL if:
   - Anomaly_rate in 10min window < 20%
   - Confidence trend is "falling" for at least 30min
   - All metrics in safe ranges (capacity > 70%, days_of_supply > 10, delay < 24hrs)
   - No high-priority events in current data

4. **Confidence Calibration**:
   - 6-hour persistent anomaly: confidence ≥ 0.85
   - 3-hour persistent anomaly: confidence ≥ 0.75
   - 1-hour persistent anomaly: confidence ≥ 0.65
   - New anomaly (first detection): confidence 0.50-0.70

5. **Evidence Requirements**: Include specific temporal observations:
   - "Capacity at 28% for 3+ hours (6-hour avg: 31%)"
   - "Anomaly rate rising: 10min=80%, 30min=65%, 1hour=45%"
   - "Confidence increased from 0.65 → 0.82 over last hour"

6. **Rate of Change**: If confidence trend is "rising" rapidly (>0.15 in 30min), \
   this signals urgent deterioration. Increase confidence and add "URGENT" to action.

Respond ONLY with JSON in this exact structure, no other text:
{
  "timestamp": "ISO-8601",
  "uc1": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."},
  "uc2": {"status": "...", "confidence": 0.0, "evidence": ["..."], "action": "..."}
}

Status must be exactly "NORMAL" or "ANOMALY_DETECTED".
Confidence must be 0.0-1.0 (use temporal calibration rules above).
Evidence must include temporal context from the analysis provided.
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
    """Periodically analyzes buffered events via Bedrock with temporal learning."""

    def __init__(self, collector: EventCollector):
        self.collector = collector
        self._client = boto3.client("bedrock-runtime", region_name=config.bedrock_region)
        self._running = False
        self.last_result: dict | None = None

        # Calculate max history based on temporal window and analysis interval
        # e.g., 6 hours * 3600 seconds / 30 seconds per cycle = 720 cycles
        cycles_per_window = int((config.temporal_window_hours * 3600) / config.analysis_interval)
        self.max_history = max(cycles_per_window, 50)  # Minimum 50 for safety
        self.result_history: deque[dict] = deque(maxlen=self.max_history)

        self.analysis_count = 0
        self._consecutive_failures = 0
        self._models = [config.bedrock_model_id]
        if config.bedrock_fallback_model_id:
            self._models.append(config.bedrock_fallback_model_id)

        log.info(
            "Analyzer initialized with temporal window: %.1f hours (%d cycles max history)",
            config.temporal_window_hours, self.max_history
        )

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

    def _build_temporal_trend_summary(self) -> dict:
        """Analyze trends from recent history (last 6 hours)."""
        if not self.result_history:
            return {}

        history_list = list(self.result_history)

        # Get samples from different time windows for trend analysis
        # Last 10 mins, 30 mins, 1 hour, 3 hours, 6 hours
        samples = {
            "10min": history_list[-20:] if len(history_list) >= 20 else history_list,  # 20 cycles = 10 min
            "30min": history_list[-60:] if len(history_list) >= 60 else history_list,  # 60 cycles = 30 min
            "1hour": history_list[-120:] if len(history_list) >= 120 else history_list,  # 120 cycles = 1 hour
            "3hour": history_list[-360:] if len(history_list) >= 360 else history_list,  # 360 cycles = 3 hours
            "6hour": history_list,  # All available history
        }

        trends = {}
        for uc_key in ["uc1", "uc2"]:
            uc_trends = {}

            for window, data in samples.items():
                if not data:
                    continue

                statuses = [r.get(uc_key, {}).get("status") for r in data if r.get(uc_key)]
                confidences = [r.get(uc_key, {}).get("confidence", 0) for r in data if r.get(uc_key)]

                if not confidences:
                    continue

                anomaly_count = sum(1 for s in statuses if s == "ANOMALY_DETECTED")
                avg_confidence = sum(confidences) / len(confidences)

                # Trend direction
                if len(confidences) >= 2:
                    recent_avg = sum(confidences[-5:]) / min(5, len(confidences[-5:]))
                    older_avg = sum(confidences[:5]) / min(5, len(confidences[:5]))
                    trend_direction = "rising" if recent_avg > older_avg + 0.05 else \
                                    "falling" if recent_avg < older_avg - 0.05 else "stable"
                else:
                    trend_direction = "stable"

                uc_trends[window] = {
                    "anomaly_count": anomaly_count,
                    "total_cycles": len(data),
                    "anomaly_rate": anomaly_count / len(data) if data else 0,
                    "avg_confidence": avg_confidence,
                    "latest_confidence": confidences[-1] if confidences else 0,
                    "trend": trend_direction,
                }

            trends[uc_key] = uc_trends

        return trends

    def _build_prompt(self, event_summary: str) -> str:
        """Build the full user prompt including multi-cycle temporal analysis."""
        now = datetime.now(timezone.utc).isoformat()
        parts = [f"Analyze these recent events (collected at {now}):\n\n{event_summary}"]

        # Build comprehensive temporal context from 6 hours of history
        if self.result_history:
            parts.append("\n\n" + "="*80)
            parts.append("TEMPORAL ANALYSIS CONTEXT (Last 6 Hours)")
            parts.append("="*80 + "\n")

            # Get trend analysis
            trends = self._build_temporal_trend_summary()

            # Recent history summary (last 10 analyses)
            recent_history = list(self.result_history)[-10:]

            parts.append("### Recent Analysis History (Last 10 Cycles)\n")
            parts.append("Cycle# | Time | UC1 Status | UC1 Conf | UC2 Status | UC2 Conf")
            parts.append("-" * 70)

            for result in recent_history:
                cycle = result.get("cycle", "?")
                timestamp = result.get("timestamp", "?")[:19]  # Trim to YYYY-MM-DDTHH:MM:SS

                uc1 = result.get("uc1", {})
                uc1_status = uc1.get("status", "UNKNOWN")[:6]  # Shorten for table
                uc1_conf = uc1.get("confidence", 0)

                uc2 = result.get("uc2", {})
                uc2_status = uc2.get("status", "UNKNOWN")[:6]
                uc2_conf = uc2.get("confidence", 0)

                parts.append(
                    f"{cycle:>6} | {timestamp} | {uc1_status:>10} | {uc1_conf:>7.2%} | "
                    f"{uc2_status:>10} | {uc2_conf:>7.2%}"
                )

            # Trend analysis for each use case
            for uc_key, uc_label in [("uc1", "UC1 (Supply Chain)"), ("uc2", "UC2 (App Store)")]:
                if uc_key not in trends:
                    continue

                uc_trends = trends[uc_key]
                parts.append(f"\n### {uc_label} - Temporal Trends\n")

                # Multi-window trend analysis
                for window in ["10min", "30min", "1hour", "3hour", "6hour"]:
                    if window not in uc_trends:
                        continue

                    t = uc_trends[window]
                    parts.append(
                        f"**{window:>6}**: {t['anomaly_count']:>3}/{t['total_cycles']:>3} anomalies "
                        f"({t['anomaly_rate']:>5.1%}) | Avg Conf: {t['avg_confidence']:>5.1%} | "
                        f"Latest: {t['latest_confidence']:>5.1%} | Trend: {t['trend']}"
                    )

                # Most recent analysis details
                if self.last_result and uc_key in self.last_result:
                    last_uc = self.last_result[uc_key]
                    parts.append(f"\n**Previous Analysis Details (Cycle #{self.analysis_count}):**")
                    parts.append(f"Status: {last_uc.get('status', 'UNKNOWN')}")
                    parts.append(f"Confidence: {last_uc.get('confidence', 0):.1%}")
                    parts.append(f"Action: {last_uc.get('action', 'N/A')}")

                    evidence = last_uc.get('evidence', [])
                    if evidence:
                        parts.append("Evidence:")
                        for i, e in enumerate(evidence[:3], 1):
                            parts.append(f"  {i}. {e}")

            parts.append("\n" + "="*80)
            parts.append("ANALYSIS INSTRUCTIONS")
            parts.append("="*80 + "\n")

            # Enhanced instructions with temporal awareness
            parts.append(
                "Based on the temporal trends above:\n\n"
                "1. **Persistent Anomalies**: If an anomaly has been detected consistently over "
                "multiple time windows (e.g., 30min and 1hour show high anomaly rates), you MUST "
                "continue reporting ANOMALY_DETECTED with INCREASED confidence.\n\n"
                "2. **Escalating Situations**: If the trend is 'rising' and anomaly rates are "
                "increasing across time windows (10min > 30min > 1hour), this indicates a "
                "WORSENING situation. Increase confidence and emphasize urgency in your action.\n\n"
                "3. **Improving Situations**: If the trend is 'falling' and recent anomaly rates "
                "(10min, 30min) are lower than historical rates (3hour, 6hour), the situation "
                "may be resolving. You can consider lowering confidence or transitioning to NORMAL "
                "if metrics have returned to safe ranges.\n\n"
                "4. **Flip-Flop Prevention**: If the 6-hour window shows consistent anomalies "
                "(>50% anomaly rate), do NOT report NORMAL unless you see clear sustained "
                "improvement across ALL time windows.\n\n"
                "5. **Rate of Change**: Pay attention to velocity. A confidence trend that went "
                "from 0.50 → 0.75 → 0.87 in 30 minutes indicates rapid deterioration and should "
                "increase your confidence and urgency.\n\n"
                "6. **Safe Range Criteria** (only declare NORMAL if ALL are true):\n"
                "   - Capacity > 70% (supply chain)\n"
                "   - Days of supply > 10 (inventory)\n"
                "   - Delay hours < 24 (logistics)\n"
                "   - No escalations for flagged apps (compliance)\n"
                "   - Anomaly rate in last 30min < 20%\n"
                "   - Confidence trend is 'falling' or 'stable'\n"
            )

        return "\n".join(parts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(log, logging.WARNING),
        reraise=True,
    )
    def _invoke_bedrock_with_retry(self, prompt: str, model_id: str) -> dict | None:
        """Call Bedrock with retry logic. Raises on failure after retries exhausted."""
        body = json.dumps({
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": 16000,
            "thinking": {
                "type": "enabled",
                "budget_tokens": 10000,
            },
            "system": SYSTEM_PROMPT,
            "messages": [
                {"role": "user", "content": prompt},
            ],
        })

        response = self._client.invoke_model(
            modelId=model_id,
            contentType="application/json",
            accept="application/json",
            body=body,
        )

        result = json.loads(response["body"].read())
        content_blocks = result.get("content", [])

        # Iterate through content blocks to find reasoning and text
        reasoning_text = None
        response_text = None

        for block in content_blocks:
            if block.get("type") == "thinking":
                reasoning_text = block.get("thinking", "")
                log.info("Extended thinking: %d chars", len(reasoning_text))
            elif block.get("type") == "text":
                response_text = block.get("text", "")

        if not response_text:
            log.error("No text block found in Bedrock response")
            raise ValueError("Bedrock response contained no text block")

        log.debug("Raw Bedrock response (first 500 chars): %s", response_text[:500])

        # Parse JSON from the text block
        text = response_text
        if "```json" in text:
            text = text.split("```json", 1)[1].rsplit("```", 1)[0]
        elif "```" in text:
            text = text.split("```", 1)[1].rsplit("```", 1)[0]

        try:
            parsed = json.loads(text.strip())
        except json.JSONDecodeError:
            parsed = None

        if not parsed:
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    parsed = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass

        if not parsed:
            log.error("Could not parse JSON from Bedrock response: %s", text[:1000])
            raise ValueError(f"Bedrock returned unparseable response: {text[:300]}")

        # Attach reasoning text to the result for email inclusion
        if reasoning_text:
            parsed["reasoning"] = reasoning_text

        # Record which model was used
        parsed["model_used"] = model_id

        return parsed

    def _invoke_bedrock(self, prompt: str) -> dict | None:
        """Call Bedrock with model fallback. Tries primary then fallback model."""
        for i, model_id in enumerate(self._models):
            try:
                log.debug("Attempting Bedrock call with model: %s", model_id)
                result = self._invoke_bedrock_with_retry(prompt, model_id)
                if i > 0:
                    log.warning("Primary model failed, used fallback: %s", model_id)
                return result
            except Exception as e:
                if i < len(self._models) - 1:
                    log.warning(
                        "Model %s failed: %s. Trying fallback model...",
                        model_id, e
                    )
                else:
                    log.error("All models failed. Last error: %s: %s", type(e).__name__, e)
                    raise

    async def run(self):
        """Periodic analysis loop."""
        self._running = True
        log.info(
            "Analyzer started — running every %.0fs with model %s (fallback: %s)",
            config.analysis_interval, config.bedrock_model_id,
            config.bedrock_fallback_model_id or "none",
        )
        await asyncio.sleep(min(config.analysis_interval, 15))

        while self._running:
            total_events = sum(len(s.events) for s in self.collector.sources)
            if total_events == 0:
                log.info("No events collected yet, skipping analysis")
                await asyncio.sleep(config.analysis_interval)
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

            # Time the analysis
            start_time = time.time()
            try:
                result = await loop.run_in_executor(None, self._invoke_bedrock, prompt)
                analysis_duration_seconds.observe(time.time() - start_time)
            except Exception as e:
                self._consecutive_failures += 1
                analysis_duration_seconds.observe(time.time() - start_time)

                # Track which model failed
                model_used = config.bedrock_model_id
                if hasattr(e, '__cause__') and hasattr(e.__cause__, 'model_id'):
                    model_used = e.__cause__.model_id
                analysis_failures_total.labels(model=model_used).inc()

                log.warning(
                    "Analysis cycle %d failed (%d consecutive): %s: %s",
                    self.analysis_count + 1, self._consecutive_failures,
                    type(e).__name__, e,
                )
                result = None
                if self._consecutive_failures >= 3:
                    backoff = min(config.analysis_interval * 2, 120)
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

                # Update metrics
                analysis_cycles_total.inc()
                high_priority_events.set(hp_count)

                for uc_key in ["uc1", "uc2"]:
                    uc = result.get(uc_key, {})
                    status = uc.get("status", "UNKNOWN")
                    confidence = uc.get("confidence", 0)

                    anomaly_confidence.labels(use_case=uc_key.upper()).set(confidence)

                    if status == "ANOMALY_DETECTED":
                        anomalies_detected_total.labels(use_case=uc_key.upper()).inc()

                # Send email notification
                await asyncio.get_event_loop().run_in_executor(
                    None, send_analysis_email, result,
                )
            else:
                log.warning("Analysis cycle %d produced no result", self.analysis_count + 1)

            await asyncio.sleep(config.analysis_interval)

    def _log_result(self, result: dict):
        """Pretty-print the analysis result with temporal context."""
        # Get temporal trends for logging
        trends = self._build_temporal_trend_summary()

        for uc_key in ["uc1", "uc2"]:
            uc = result.get(uc_key, {})
            status = uc.get("status", "UNKNOWN")
            confidence = uc.get("confidence", 0)
            action = uc.get("action", "N/A")
            evidence = uc.get("evidence", [])

            icon = "🔴" if status == "ANOMALY_DETECTED" else "🟢"

            # Get temporal trend info if available
            temporal_info = ""
            if uc_key in trends and "30min" in trends[uc_key]:
                t30 = trends[uc_key]["30min"]
                temporal_info = f" | 30min: {t30['anomaly_rate']:.0%} anomalies, trend={t30['trend']}"

            log.info(
                "%s %s: %s (confidence=%.0f%%)%s",
                icon, uc_key.upper(), status, confidence * 100, temporal_info,
            )
            log.info("   Action: %s", action)
            for e in evidence[:3]:
                log.info("   ↳ %s", e)

            # Log temporal awareness summary
            if uc_key in trends:
                uc_trends = trends[uc_key]
                if "6hour" in uc_trends and uc_trends["6hour"]["total_cycles"] >= 10:
                    t6h = uc_trends["6hour"]
                    log.info(
                        "   📊 6-hour context: %d/%d cycles anomalies (%.0f%%), conf trend: %s",
                        t6h["anomaly_count"], t6h["total_cycles"],
                        t6h["anomaly_rate"] * 100, t6h["trend"]
                    )

    def stop(self):
        self._running = False
