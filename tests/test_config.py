"""Tests for configuration validation."""
import pytest
from pydantic import ValidationError
from agent.config import AgentConfig


class TestConfigValidation:
    """Test Pydantic configuration validation."""

    def test_default_config_is_valid(self):
        """Default configuration should be valid."""
        config = AgentConfig()
        assert config.poll_interval == 3.0
        assert config.analysis_interval == 30.0
        assert config.dashboard_port == 8080

    def test_poll_interval_validation(self):
        """Poll interval must be between 0.1 and 60."""
        with pytest.raises(ValidationError):
            AgentConfig(poll_interval=0.05)  # Too low

        with pytest.raises(ValidationError):
            AgentConfig(poll_interval=100)  # Too high

        # Valid values should work
        config = AgentConfig(poll_interval=5.0)
        assert config.poll_interval == 5.0

    def test_event_window_size_validation(self):
        """Event window size must be between 10 and 10000."""
        with pytest.raises(ValidationError):
            AgentConfig(event_window_size=5)  # Too low

        with pytest.raises(ValidationError):
            AgentConfig(event_window_size=20000)  # Too high

        # Valid value should work
        config = AgentConfig(event_window_size=500)
        assert config.event_window_size == 500

    def test_dashboard_port_validation(self):
        """Dashboard port must be valid (1024-65535)."""
        with pytest.raises(ValidationError):
            AgentConfig(dashboard_port=80)  # Too low (privileged)

        with pytest.raises(ValidationError):
            AgentConfig(dashboard_port=70000)  # Too high

        # Valid port should work
        config = AgentConfig(dashboard_port=3000)
        assert config.dashboard_port == 3000

    def test_analysis_interval_validation(self):
        """Analysis interval must be between 5 and 600."""
        with pytest.raises(ValidationError):
            AgentConfig(analysis_interval=1.0)  # Too low

        with pytest.raises(ValidationError):
            AgentConfig(analysis_interval=1000)  # Too high

        # Valid value should work
        config = AgentConfig(analysis_interval=60.0)
        assert config.analysis_interval == 60.0

    def test_email_enabled_parses_strings(self):
        """email_enabled should accept boolean or string."""
        config1 = AgentConfig(email_enabled=True)
        assert config1.email_enabled is True

        config2 = AgentConfig(email_enabled=False)
        assert config2.email_enabled is False
