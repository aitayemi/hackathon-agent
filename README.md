# Hackathon Agent — Anomaly Detection

Consumes events from UC1 (Supply Chain) and UC2 (App Store Compliance) simulators,
buffers them in memory, and periodically sends them to Amazon Bedrock for anomaly analysis.

## Architecture

```
sim-uc1 :8001 ──poll──┐
                       ├──▶ EventCollector ──▶ Analyzer ──▶ Bedrock Claude
sim-uc2 :8002 ──poll──┘         │                  │
                          rolling buffer      JSON verdicts
                          (last 200/source)   every 30s
                                │
                          Dashboard :8080  ◀── WebSocket ──▶  Browser
```

## Local Development

```bash
# Install
pip install -e .

# Run (point to local port-forwarded simulators)
UC1_BASE_URL=http://localhost:8001 \
UC2_BASE_URL=http://localhost:8002 \
BEDROCK_REGION=us-west-2 \
hackathon-agent
```

## EKS Deployment

1. Build and push the image:
   ```bash
   docker build -t <ecr-repo>/hackathon-agent:latest .
   docker push <ecr-repo>/hackathon-agent:latest
   ```

2. Set up IRSA — the agent's service account needs an IAM role with `bedrock:InvokeModel`.
   Update the role ARN in `k8s/agent.yaml`.

3. Deploy:
   ```bash
   kubectl apply -f k8s/agent.yaml
   ```

4. Watch the logs:
   ```bash
   kubectl logs -f deployment/hackathon-agent -n techcompany-sim
   ```

## Configuration (Environment Variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `UC1_BASE_URL` | `http://techcompany-sim-uc1.techcompany-sim:8001` | UC1 simulator endpoint |
| `UC2_BASE_URL` | `http://techcompany-sim-uc2.techcompany-sim:8002` | UC2 simulator endpoint |
| `POLL_INTERVAL` | `3.0` | Seconds between poll cycles |
| `ANALYSIS_INTERVAL` | `30.0` | Seconds between Bedrock analysis runs |
| `BEDROCK_REGION` | `us-west-2` | AWS region for Bedrock |
| `BEDROCK_MODEL_ID` | `anthropic.claude-3-5-haiku-20241022-v1:0` | Bedrock model ID |
| `EVENT_WINDOW_SIZE` | `200` | Max events buffered per source |
| `DASHBOARD_PORT` | `8080` | Port for the live web dashboard |

## Dashboard

The agent includes a real-time web dashboard at `http://localhost:8080` (or whatever `DASHBOARD_PORT` is set to).

It shows:
- Live event counts for UC1 (Supply Chain) and UC2 (App Store Compliance)
- Per-source collection stats with buffer utilization bars
- Anomaly analysis results with confidence gauges, evidence, and recommended actions
- A live event feed streaming raw events as they arrive

The dashboard uses WebSockets for real-time updates — no polling, no refresh needed.
