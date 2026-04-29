# Supply Chain Disruption Detection Agent 

An intelligent anomaly detection agent that consumes real-time events from UC1 (Supply Chain) and UC2 (App Store Compliance) simulators, buffers them in memory, and leverages Amazon Bedrock Claude models for intelligent anomaly analysis with automatic alerting.

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          HACKATHON AGENT (v0.1.0)                               │
│                                                                                  │
│  ┌──────────────┐   HTTP/SSE    ┌─────────────────────────────────────┐        │
│  │  sim-uc1     │──────poll─────▶│                                     │        │
│  │  :8001       │    (3s)        │      EventCollector                 │        │
│  │ Supply Chain │                │                                     │        │
│  └──────────────┘                │  • Polls simulators every 3s        │        │
│                                  │  • Deduplicates events (fingerprint)│        │
│  ┌──────────────┐   HTTP/SSE    │  • Rolling buffer (200 events/src)  │        │
│  │  sim-uc2     │──────poll─────▶│  • Priority detection               │        │
│  │  :8002       │    (3s)        │                                     │        │
│  │ App Store    │                └────────────┬────────────────────────┘        │
│  │ Compliance   │                             │                                 │
│  └──────────────┘                             │ buffered events                 │
│                                                ▼                                 │
│                                  ┌─────────────────────────────────────┐        │
│                                  │         Analyzer                     │        │
│                                  │                                      │        │
│                                  │  • Runs every 30s                    │        │
│                                  │  • Retry logic (3x, exp backoff)    │        │
│                                  │  • Model fallback (Sonnet→Haiku)    │        │
│                                  └────────────┬────────────────────────┘        │
│                                               │                                  │
│                                               │ invoke_model()                   │
│                                               ▼                                  │
│                      ┌────────────────────────────────────────┐                 │
│                      │     Amazon Bedrock                      │                 │
│                      │                                         │                 │
│                      │  Primary:   Claude Sonnet 4.5          │                 │
│                      │  Fallback:  Claude Haiku 4.5           │                 │
│                      │                                         │                 │
│                      │  Returns: Anomaly status, confidence,  │                 │
│                      │           evidence, recommendations    │                 │
│                      └────────────────┬───────────────────────┘                 │
│                                       │                                          │
│                                       │ analysis results                         │
│                                       ▼                                          │
│                      ┌────────────────────────────────────────┐                 │
│                      │         Notifier                        │                 │
│                      │                                         │                 │
│                      │  • Email throttling (5 min default)    │                 │
│                      │  • Status change detection              │                 │
│                      │  • Prometheus metrics                   │                 │
│                      └────────────┬───────────────────────────┘                 │
│                                   │                                              │
│                                   │ SMTP                                         │
│                                   ▼                                              │
│                      ┌────────────────────────────────────────┐                 │
│                      │       Email Server (SMTP)               │                 │
│                      │                                         │                 │
│                      │  Anomaly alerts sent to configured      │                 │
│                      │  recipients with analysis details       │                 │
│                      └─────────────────────────────────────────┘                 │
│                                                                                  │
│  ┌──────────────────────────────────────────────────────────────────────┐      │
│  │                    Dashboard & Monitoring (FastAPI)                   │      │
│  │                                                                        │      │
│  │  HTTP :8080                                                           │      │
│  │  ├─ /                  Web dashboard (WebSocket real-time updates)   │      │
│  │  ├─ /ws                WebSocket endpoint for live event feed         │      │
│  │  ├─ /health            Kubernetes liveness probe                      │      │
│  │  ├─ /ready             Kubernetes readiness probe                     │      │
│  │  └─ /metrics           Prometheus metrics (13 metrics)                │      │
│  │                                                                        │      │
│  │  Displays:                                                            │      │
│  │  • Live event counts & buffer utilization                             │      │
│  │  • Anomaly analysis with confidence gauges                            │      │
│  │  • Evidence & recommended actions                                     │      │
│  │  • Real-time event stream                                             │      │
│  └────────────────────────────────────────────────────────────────────────┘      │
│                                   ▲                                              │
│                                   │ WebSocket                                    │
│                                   │                                              │
│                              ┌────┴─────┐                                        │
│                              │ Browser  │                                        │
│                              └──────────┘                                        │
└─────────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ scrape /metrics
                                   ▼
                        ┌────────────────────┐
                        │    Prometheus      │
                        │   Monitoring       │
                        └────────────────────┘
```

### Data Flow

1. **Event Collection** (every 3 seconds)
   - Poll UC1/UC2 simulators via HTTP SSE
   - Deduplicate events using ID or fingerprint
   - Buffer last 200 events per source
   - Track high-priority events

2. **Anomaly Analysis** (every 30 seconds)
   - Send buffered events to Bedrock Claude
   - Retry failed calls 3x with exponential backoff (4s → 16s → 60s)
   - Fallback to Haiku model if Sonnet fails
   - Parse structured JSON response (status, confidence, evidence, actions)

3. **Alerting & Notification**
   - Detect status changes (NORMAL ↔ ANOMALY)
   - Throttle emails (1 per 5 minutes for same status)
   - Send detailed anomaly reports via SMTP
   - Track metrics (sent, throttled, failed)

4. **Real-time Visualization**
   - WebSocket-based dashboard updates
   - Live event feed
   - Anomaly confidence gauges
   - Buffer utilization monitoring

## Features

### 🔒 **Reliability & Resilience**
- **Automatic Retries**: 3 retry attempts with exponential backoff (4s → 16s → 60s) for transient Bedrock failures
- **Model Fallback**: Automatic failover from Claude Sonnet 4.5 to Claude Haiku 4.5 if primary model unavailable
- **Event Deduplication**: Prevents duplicate event processing across overlapping polls
- **Health Checks**: Kubernetes-ready liveness and readiness probes

### 🧠 **Temporal Learning & Multi-Cycle Analysis** (NEW!)
- **6-Hour Memory Window**: Maintains up to 6 hours of analysis history (configurable)
- **Multi-Window Trend Analysis**: Analyzes patterns across 10min, 30min, 1hour, 3hour, and 6hour windows
- **Rate-of-Change Detection**: Identifies escalating vs. improving situations
- **Persistent Anomaly Recognition**: Tracks anomaly rates and confidence trends over time
- **Temporal Reasoning**: Model receives comprehensive historical context to avoid false positives and flip-flopping
- **Confidence Calibration**: Automatic confidence adjustment based on anomaly persistence (6hr persistent = 85%+ confidence)

### 📧 **Smart Notifications**
- **Email Throttling**: Configurable rate limiting (default: 5 minutes) prevents alert spam during persistent anomalies
- **Status Change Detection**: Only alerts when anomaly status changes or throttle interval elapses
- **Detailed Reports**: Includes confidence scores, evidence, and recommended actions
- **SMTP Integration**: Configurable email server support

### 📊 **Observability**
- **Prometheus Metrics**: 13 comprehensive metrics covering collection, analysis, and alerting
- **Structured Logging**: JSON logs in Kubernetes, human-readable console locally (auto-detected)
- **Real-time Dashboard**: WebSocket-based live updates with no polling overhead
- **Health Endpoints**: `/health`, `/ready`, and `/metrics` for monitoring integration

### ⚙️ **Configuration & Validation**
- **Pydantic Validation**: Type-checked configuration with range validation
- **Environment Variables**: Flexible configuration via env vars or `.env` file
- **Sensible Defaults**: Works out-of-the-box with minimal configuration

### 🧪 **Production Ready**
- **34 Unit Tests**: Comprehensive test coverage of critical paths (~80%)
- **CI/CD Friendly**: Docker containerized with health checks
- **Kubernetes Native**: IRSA support, proper resource limits, pod probes

## Local Development

```bash
# Install with development dependencies
pip install -e ".[dev]"

# Run locally (point to local simulators)
UC1_BASE_URL=http://localhost:8001 \
UC2_BASE_URL=http://localhost:8002 \
BEDROCK_REGION=us-west-2 \
SMTP_HOST=smtp.example.com \
SMTP_PORT=587 \
SMTP_FROM=alerts@example.com \
SMTP_TO=oncall@example.com \
SMTP_USERNAME=user \
SMTP_PASSWORD=pass \
hackathon-agent

# Run with custom configuration
EMAIL_THROTTLE_INTERVAL=600 \
ANALYSIS_INTERVAL=60 \
EVENT_WINDOW_SIZE=500 \
hackathon-agent

# Run tests
pytest

# Run tests with coverage
pytest --cov=agent --cov-report=term-missing --cov-report=html

# View coverage report
open htmlcov/index.html
```

## Testing

The project includes a comprehensive test suite with 34 unit tests covering critical functionality.

### Running Tests

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run all tests
pytest

# Run with verbose output
pytest -v

# Run specific test file
pytest tests/test_analyzer.py

# Run with coverage report
pytest --cov=agent --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=agent --cov-report=html
open htmlcov/index.html
```

### Test Coverage

**Test Files:**
- `tests/test_analyzer.py` - 15 tests for high-priority detection and analysis logic
- `tests/test_collector.py` - 8 tests for event deduplication and collection
- `tests/test_config.py` - 6 tests for Pydantic validation
- `tests/test_notifier.py` - 5 tests for email throttling

**Coverage:** ~80% of critical paths including:
- Event deduplication logic
- High-priority event detection
- Email throttling and status change detection
- Configuration validation with edge cases
- Error handling and retry logic

See `TESTING.md` for detailed test documentation.

## Deployment

### Docker Build

```bash
# Build the image
docker build -t <ecr-repo>/hackathon-agent:latest .

# Test locally with Docker
docker run --rm \
  -e UC1_BASE_URL=http://host.docker.internal:8001 \
  -e UC2_BASE_URL=http://host.docker.internal:8002 \
  -e BEDROCK_REGION=us-west-2 \
  -e SMTP_HOST=smtp.example.com \
  -e SMTP_PORT=587 \
  -e SMTP_FROM=alerts@example.com \
  -e SMTP_TO=oncall@example.com \
  -p 8080:8080 \
  <ecr-repo>/hackathon-agent:latest

# Push to ECR
aws ecr get-login-password --region us-west-2 | docker login --username AWS --password-stdin <ecr-repo>
docker push <ecr-repo>/hackathon-agent:latest
```

### Kubernetes Deployment

#### Prerequisites

1. **IRSA Setup**: The agent's service account needs an IAM role with Bedrock permissions:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": [
           "bedrock:InvokeModel",
           "bedrock:InvokeModelWithResponseStream"
         ],
         "Resource": [
           "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0",
           "arn:aws:bedrock:us-west-2::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
         ]
       }
     ]
   }
   ```

2. **SMTP Credentials**: Store in Kubernetes Secret:
   ```bash
   kubectl create secret generic hackathon-agent-smtp \
     --from-literal=username=<smtp-username> \
     --from-literal=password=<smtp-password> \
     -n techcompany-sim
   ```

#### Deploy

1. Update the IAM role ARN in `k8s/agent.yaml`:
   ```yaml
   serviceAccount:
     annotations:
       eks.amazonaws.com/role-arn: arn:aws:iam::<account>:role/<irsa-role>
   ```

2. Update SMTP configuration in `k8s/agent.yaml`:
   ```yaml
   env:
     - name: SMTP_HOST
       value: "smtp.example.com"
     - name: SMTP_PORT
       value: "587"
     - name: SMTP_FROM
       value: "alerts@example.com"
     - name: SMTP_TO
       value: "oncall@example.com"
   ```

3. Deploy to Kubernetes:
   ```bash
   kubectl apply -f k8s/agent.yaml
   ```

4. Verify deployment:
   ```bash
   # Check pod status
   kubectl get pods -n techcompany-sim -l app=hackathon-agent
   
   # Watch logs
   kubectl logs -f deployment/hackathon-agent -n techcompany-sim
   
   # Check health
   kubectl port-forward svc/hackathon-agent 8080:8080 -n techcompany-sim
   curl http://localhost:8080/health
   curl http://localhost:8080/ready
   curl http://localhost:8080/metrics
   ```

#### Monitoring Setup

Add Prometheus scrape configuration:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: monitoring
data:
  prometheus.yml: |
    scrape_configs:
      - job_name: 'hackathon-agent'
        kubernetes_sd_configs:
          - role: pod
            namespaces:
              names:
                - techcompany-sim
        relabel_configs:
          - source_labels: [__meta_kubernetes_pod_label_app]
            regex: hackathon-agent
            action: keep
          - source_labels: [__meta_kubernetes_pod_ip]
            target_label: __address__
            replacement: $1:8080
          - source_labels: [__meta_kubernetes_pod_name]
            target_label: pod
```

#### Troubleshooting

```bash
# Check pod events
kubectl describe pod -n techcompany-sim -l app=hackathon-agent

# Check resource usage
kubectl top pod -n techcompany-sim -l app=hackathon-agent

# Test Bedrock connectivity (exec into pod)
kubectl exec -it deployment/hackathon-agent -n techcompany-sim -- /bin/sh
python -c "import boto3; client = boto3.client('bedrock-runtime', region_name='us-west-2'); print('OK')"

# Check SMTP connectivity
telnet smtp.example.com 587

# View readiness probe failures
kubectl get events -n techcompany-sim --field-selector involvedObject.name=hackathon-agent
```

## Configuration (Environment Variables)

### Core Settings

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `UC1_BASE_URL` | `http://techcompany-sim-uc1.techcompany-sim:8001` | - | UC1 (Supply Chain) simulator endpoint |
| `UC2_BASE_URL` | `http://techcompany-sim-uc2.techcompany-sim:8002` | - | UC2 (App Store) simulator endpoint |
| `POLL_INTERVAL` | `3.0` | 0.1 - 60.0 | Seconds between poll cycles |
| `ANALYSIS_INTERVAL` | `30.0` | 5.0 - 600.0 | Seconds between Bedrock analysis runs |
| `EVENT_WINDOW_SIZE` | `200` | 10 - 10000 | Max events buffered per source |
| `TEMPORAL_WINDOW_HOURS` | `6.0` | 0.5 - 24.0 | Hours of history for temporal learning |
| `DASHBOARD_PORT` | `8080` | 1024 - 65535 | Port for the live web dashboard |

### AWS Bedrock Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `BEDROCK_REGION` | `us-west-2` | AWS region for Bedrock |
| `BEDROCK_MODEL_ID` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | Primary Bedrock model ID (Sonnet 4.5) |
| `BEDROCK_FALLBACK_MODEL_ID` | `anthropic.claude-haiku-4-5-20251001-v1:0` | Fallback model if primary fails (Haiku 4.5) |

### Email/SMTP Configuration

| Variable | Required | Description |
|----------|----------|-------------|
| `SMTP_HOST` | Yes | SMTP server hostname |
| `SMTP_PORT` | Yes | SMTP server port (usually 587 for TLS) |
| `SMTP_FROM` | Yes | Sender email address |
| `SMTP_TO` | Yes | Recipient email address for alerts |
| `SMTP_USERNAME` | No | SMTP authentication username (if required) |
| `SMTP_PASSWORD` | No | SMTP authentication password (if required) |
| `EMAIL_THROTTLE_INTERVAL` | `300` | Seconds between emails for same anomaly status |

### Logging Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_FORMAT` | `console` | `console` for human-readable, `json` for structured logs (auto-detected in K8s) |

### Configuration Validation

All configuration values are validated at startup using Pydantic:
- Type checking (strings, integers, floats)
- Range validation for numeric values
- URL format validation
- Descriptive error messages for invalid configuration

Example validation error:
```
ValidationError: 1 validation error for Config
poll_interval
  Input should be less than or equal to 60.0 [type=less_than_equal, input_value=120.0]
```

## Dashboard & Monitoring

### Web Dashboard

The agent includes a real-time web dashboard at `http://localhost:8080` (configurable via `DASHBOARD_PORT`).

**Features:**
- **Live Event Counts**: Real-time counters for UC1 (Supply Chain) and UC2 (App Store Compliance)
- **Buffer Utilization**: Visual progress bars showing buffer fill levels per source
- **Anomaly Analysis**: Confidence gauges, status indicators, evidence, and recommended actions
- **Event Feed**: Streaming display of raw events as they arrive
- **WebSocket Updates**: Zero-latency updates with no polling or page refresh needed

**Access:**
```bash
# Local development
open http://localhost:8080

# Kubernetes (port-forward)
kubectl port-forward svc/hackathon-agent 8080:8080 -n techcompany-sim
open http://localhost:8080
```

### Health Endpoints

The agent exposes three monitoring endpoints:

| Endpoint | Purpose | K8s Probe | Response |
|----------|---------|-----------|----------|
| `/health` | Liveness probe | Yes | `{"status": "healthy"}` if process alive |
| `/ready` | Readiness probe | Yes | `{"status": "ready"}` if collecting events |
| `/metrics` | Prometheus metrics | - | Prometheus text format |

**Kubernetes Probe Configuration:**
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 10
```

### Prometheus Metrics

The `/metrics` endpoint exposes 13 comprehensive metrics:

**Event Collection Metrics:**
```
events_collected_total{use_case, source}      # Total events collected
events_deduplicated_total{use_case, source}   # Duplicate events filtered
poll_errors_total{use_case, source}           # Polling failures
event_buffer_size{use_case, source}           # Current buffer size (gauge)
```

**Analysis Metrics:**
```
analysis_cycles_total                         # Completed analysis cycles
analysis_duration_seconds                     # Bedrock call duration (histogram)
analysis_failures_total{model}                # Bedrock failures by model
anomalies_detected_total{use_case}            # Total anomalies detected
anomaly_confidence{use_case}                  # Current confidence score (gauge)
high_priority_events_current                  # High-priority events in buffer (gauge)
```

**Email/Notification Metrics:**
```
emails_sent_total                             # Successfully sent emails
emails_throttled_total                        # Emails blocked by throttling
emails_failed_total                           # Email sending failures
```

**Example Prometheus Queries:**
```promql
# Event collection rate (events/sec)
rate(events_collected_total[5m])

# Analysis success rate
rate(analysis_cycles_total[5m]) / (rate(analysis_cycles_total[5m]) + rate(analysis_failures_total[5m]))

# Email throttle effectiveness
rate(emails_throttled_total[1h]) / rate(emails_sent_total[1h])

# Buffer utilization percentage
(event_buffer_size / 200) * 100

# High-priority event alerts
high_priority_events_current > 10
```

### Structured Logging

The agent uses `structlog` for structured, machine-parseable logs:

**Local Development (Console):**
```
2026-04-28 12:30:15 [info     ] Starting hackathon agent
2026-04-28 12:30:18 [info     ] Events collected               count=15 source=supply_chain use_case=UC1
2026-04-28 12:30:45 [warning  ] Analysis retry                 attempt=1 model=sonnet-v2
2026-04-28 12:30:49 [info     ] Analysis complete              anomalies=1 confidence=0.87 uc1_status=ANOMALY
```

**Kubernetes (JSON):**
```json
{"event": "Starting hackathon agent", "level": "info", "timestamp": "2026-04-28T12:30:15Z"}
{"event": "Events collected", "count": 15, "source": "supply_chain", "use_case": "UC1", "level": "info"}
{"event": "Analysis retry", "attempt": 1, "model": "sonnet-v2", "level": "warning"}
{"event": "Analysis complete", "anomalies": 1, "confidence": 0.87, "uc1_status": "ANOMALY", "level": "info"}
```

The log format is automatically detected (JSON in K8s, console elsewhere) or can be explicitly set via `LOG_FORMAT=json`.

## Email Notifications

The agent sends intelligent email alerts when anomalies are detected or when status changes occur.

### Email Throttling

To prevent alert fatigue during persistent anomalies, the agent implements smart throttling:

- **Status Change Detection**: Immediate email when status transitions (NORMAL → ANOMALY or vice versa)
- **Throttle Interval**: Configurable cooldown period (default: 5 minutes)
- **Same Status Suppression**: No emails sent if status unchanged and within throttle interval
- **Per-Status Tracking**: Independent throttling for UC1 and UC2

**Example Scenario:**
```
12:00:00 - Anomaly detected in UC1 → Email sent
12:00:30 - Still anomaly in UC1 → Suppressed (within 5 min)
12:01:00 - Still anomaly in UC1 → Suppressed (within 5 min)
12:05:01 - Still anomaly in UC1 → Email sent (throttle expired)
12:06:00 - Status changes to NORMAL → Email sent immediately (status change)
```

### Email Content

Anomaly alert emails include:

- **Subject**: `[ANOMALY] Supply Chain Disruption Detected` or `[NORMAL] Supply Chain Status Update`
- **UC1 Status**: Supply Chain analysis (NORMAL/ANOMALY) with confidence score
- **UC2 Status**: App Store Compliance analysis (NORMAL/ANOMALY) with confidence score
- **Evidence**: Key findings and patterns detected by Claude
- **Recommended Actions**: Specific steps to investigate or mitigate
- **Timestamp**: Analysis completion time

**Example Email:**
```
Subject: [ANOMALY] Supply Chain Disruption Detected

Anomaly Analysis Report

UC1 (Supply Chain): ANOMALY (confidence: 87%)
Evidence:
- Multiple late shipments detected from supplier ACME Corp
- Inventory levels for critical components dropped 40%
- 3 production delays reported in the last hour

Recommended Actions:
1. Contact ACME Corp regarding shipment delays
2. Check buffer stock for affected components
3. Notify production planning team

UC2 (App Store Compliance): NORMAL (confidence: 95%)

Analysis completed at: 2026-04-28 12:30:45 UTC
```

### SMTP Configuration

The agent supports standard SMTP servers with optional authentication:

```bash
# Required settings
SMTP_HOST=smtp.gmail.com          # SMTP server hostname
SMTP_PORT=587                     # Port (587 for TLS, 465 for SSL, 25 for plain)
SMTP_FROM=alerts@example.com      # Sender address
SMTP_TO=oncall@example.com        # Recipient address

# Optional authentication (if required by server)
SMTP_USERNAME=alerts@example.com  # SMTP auth username
SMTP_PASSWORD=app-specific-password  # SMTP auth password

# Optional throttling configuration
EMAIL_THROTTLE_INTERVAL=300       # Seconds between emails (default: 5 minutes)
```

**Common SMTP Providers:**

| Provider | Host | Port | Auth | Notes |
|----------|------|------|------|-------|
| Gmail | smtp.gmail.com | 587 | Required | Use app-specific password |
| AWS SES | email-smtp.us-west-2.amazonaws.com | 587 | Required | SMTP credentials from SES |
| SendGrid | smtp.sendgrid.net | 587 | Required | API key as password |
| Mailgun | smtp.mailgun.org | 587 | Required | SMTP credentials from Mailgun |
| Office 365 | smtp.office365.com | 587 | Required | Use full email as username |

### Testing Email Notifications

```bash
# Test SMTP connectivity
telnet smtp.example.com 587

# Test email sending (Python)
python3 << 'EOF'
import smtplib
from email.message import EmailMessage

msg = EmailMessage()
msg['Subject'] = 'Test Email'
msg['From'] = 'alerts@example.com'
msg['To'] = 'oncall@example.com'
msg.set_content('Test message from hackathon-agent')

with smtplib.SMTP('smtp.example.com', 587) as smtp:
    smtp.starttls()
    smtp.login('username', 'password')
    smtp.send_message(msg)
    print('Email sent successfully')
EOF
```

### Monitoring Email Delivery

Use Prometheus metrics to track email status:

```promql
# Total emails sent
emails_sent_total

# Email send rate
rate(emails_sent_total[1h])

# Throttled email percentage
rate(emails_throttled_total[1h]) / (rate(emails_sent_total[1h]) + rate(emails_throttled_total[1h])) * 100

# Failed email alerts
rate(emails_failed_total[5m]) > 0
```
