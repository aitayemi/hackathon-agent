"""
Prometheus metrics for agent observability.
"""
from prometheus_client import Counter, Histogram, Gauge, Info

# ── Event collection ─────────────────────────────────────────────────────────
events_collected_total = Counter(
    'events_collected_total',
    'Total events collected from simulators',
    ['use_case', 'source']
)

events_deduplicated_total = Counter(
    'events_deduplicated_total',
    'Total events deduplicated',
    ['use_case', 'source']
)

poll_errors_total = Counter(
    'poll_errors_total',
    'Total polling errors',
    ['use_case', 'source']
)

event_buffer_size = Gauge(
    'event_buffer_size',
    'Current number of events in buffer',
    ['use_case', 'source']
)

# ── Analysis ─────────────────────────────────────────────────────────────────
analysis_cycles_total = Counter(
    'analysis_cycles_total',
    'Total Bedrock analysis cycles completed'
)

analysis_duration_seconds = Histogram(
    'analysis_duration_seconds',
    'Time taken for Bedrock analysis',
    buckets=[1, 5, 10, 20, 30, 60, 120]
)

analysis_failures_total = Counter(
    'analysis_failures_total',
    'Total Bedrock analysis failures',
    ['model']
)

anomalies_detected_total = Counter(
    'anomalies_detected_total',
    'Total anomalies detected',
    ['use_case']
)

anomaly_confidence = Gauge(
    'anomaly_confidence',
    'Current anomaly confidence score (0-1)',
    ['use_case']
)

high_priority_events = Gauge(
    'high_priority_events_current',
    'Current number of high-priority events in buffer'
)

# ── Email notifications ──────────────────────────────────────────────────────
emails_sent_total = Counter(
    'emails_sent_total',
    'Total emails sent'
)

emails_throttled_total = Counter(
    'emails_throttled_total',
    'Total emails throttled due to rate limiting'
)

emails_failed_total = Counter(
    'emails_failed_total',
    'Total email sending failures'
)

# ── Agent info ───────────────────────────────────────────────────────────────
agent_info = Info(
    'agent_info',
    'Agent configuration and version'
)
