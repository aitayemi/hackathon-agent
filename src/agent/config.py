"""
Agent configuration — simulator endpoints and Bedrock settings.

Inside the EKS cluster, simulators are reachable via their k8s Service names.
Override with environment variables for local development.
"""
from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class AgentConfig(BaseSettings):
    """Validated agent configuration from environment variables."""

    # ── Simulator endpoints ──────────────────────────────────────────────
    uc1_base_url: str = Field(
        default="http://techcompany-sim-uc1.techcompany-sim:8001",
        description="UC1 simulator endpoint"
    )
    uc2_base_url: str = Field(
        default="http://techcompany-sim-uc2.techcompany-sim:8002",
        description="UC2 simulator endpoint"
    )

    # ── Polling ──────────────────────────────────────────────────────────
    poll_interval: float = Field(default=3.0, ge=0.1, le=60.0)
    event_window_size: int = Field(default=200, ge=10, le=10000)

    # ── Bedrock ──────────────────────────────────────────────────────────
    bedrock_region: str = Field(default="us-west-2")
    bedrock_model_id: str = Field(
###        default="anthropic.claude-sonnet-4-5-20250929-v1:0"
        default="arn:aws:bedrock:us-west-2:440310653679:inference-profile/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
    )
    bedrock_fallback_model_id: str | None = Field(
###        default="anthropic.claude-haiku-4-5-20251001-v1:0",
        default="arn:aws:bedrock:us-west-2:440310653679:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0",
        description="Fallback model if primary fails"
    )
    analysis_interval: float = Field(default=30.0, ge=5.0, le=600.0)
    temporal_window_hours: float = Field(
        default=6.0,
        ge=0.5,
        le=24.0,
        description="Hours of history to maintain for temporal analysis"
    )

    # ── Dashboard ────────────────────────────────────────────────────────
    dashboard_port: int = Field(default=8080, ge=1024, le=65535)

    # ── Email notifications ──────────────────────────────────────────────
    smtp_host: str = Field(default="192.168.0.46")
    smtp_port: int = Field(default=25, ge=1, le=65535)
    email_from: str = Field(default="anomaly-agent@domain.com")
    email_to: str = Field(default="johnwicks@domain.com")
    email_enabled: bool = Field(default=True)
    smtp_username: str = Field(default="johnwicks")
    smtp_password: str = Field(default="johnwicks12345!")
    email_throttle_interval: float = Field(
        default=300.0,
        ge=0,
        description="Minimum seconds between emails for same anomaly status"
    )

    class Config:
        env_prefix = ""
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"


# Global config instance
config = AgentConfig()

# Backward compatibility exports
UC1_BASE_URL = config.uc1_base_url
UC2_BASE_URL = config.uc2_base_url
POLL_INTERVAL = config.poll_interval
EVENT_WINDOW_SIZE = config.event_window_size
BEDROCK_REGION = config.bedrock_region
BEDROCK_MODEL_ID = config.bedrock_model_id
ANALYSIS_INTERVAL = config.analysis_interval
DASHBOARD_PORT = config.dashboard_port
SMTP_HOST = config.smtp_host
SMTP_PORT = config.smtp_port
EMAIL_FROM = config.email_from
EMAIL_TO = config.email_to
EMAIL_ENABLED = config.email_enabled
SMTP_USERNAME = config.smtp_username
SMTP_PASSWORD = config.smtp_password

# Signal sources per use case
UC1_SOURCES = ["supplier-capacity", "logistics", "geopolitical", "inventory"]
UC2_SOURCES = ["submission-queue", "policy-kb", "submission-history", "escalation-queue"]
