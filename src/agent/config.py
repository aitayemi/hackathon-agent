"""
Agent configuration — simulator endpoints and Bedrock settings.

Inside the EKS cluster, simulators are reachable via their k8s Service names.
Override with environment variables for local development.
"""
from __future__ import annotations

import os


# ── Simulator endpoints ──────────────────────────────────────────────────────

UC1_BASE_URL = os.getenv("UC1_BASE_URL", "http://techcompany-sim-uc1.techcompany-sim:8001")
UC2_BASE_URL = os.getenv("UC2_BASE_URL", "http://techcompany-sim-uc2.techcompany-sim:8002")

# Signal sources per use case
UC1_SOURCES = ["supplier-capacity", "logistics", "geopolitical", "inventory"]
UC2_SOURCES = ["submission-queue", "policy-kb", "submission-history", "escalation-queue"]

# ── Polling ──────────────────────────────────────────────────────────────────

POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "3.0"))
EVENT_WINDOW_SIZE = int(os.getenv("EVENT_WINDOW_SIZE", "200"))

# ── Bedrock ──────────────────────────────────────────────────────────────────

BEDROCK_REGION = os.getenv("BEDROCK_REGION", "us-west-2")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "us.anthropic.claude-haiku-4-5-20251001-v1:0")
ANALYSIS_INTERVAL = float(os.getenv("ANALYSIS_INTERVAL", "30.0"))

# ── Dashboard ────────────────────────────────────────────────────────────────

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
