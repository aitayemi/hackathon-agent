"""Tests for email notifier."""
import pytest
import time
from agent.notifier import EmailThrottler


class TestEmailThrottler:
    """Test email throttling logic."""

    def test_first_email_always_sends(self):
        """First email for a status should always be allowed."""
        throttler = EmailThrottler(min_interval=10.0)
        assert throttler.should_send("UC1:ANOMALY") is True

    def test_rapid_emails_are_throttled(self):
        """Emails for same status within interval should be throttled."""
        throttler = EmailThrottler(min_interval=10.0)

        # First email allowed
        assert throttler.should_send("UC1:ANOMALY") is True

        # Immediate retry should be blocked
        assert throttler.should_send("UC1:ANOMALY") is False

    def test_different_statuses_not_throttled(self):
        """Different status keys should not throttle each other."""
        throttler = EmailThrottler(min_interval=10.0)

        assert throttler.should_send("UC1:ANOMALY") is True
        assert throttler.should_send("UC2:ANOMALY") is True
        assert throttler.should_send("UC1:NORMAL") is True

    def test_email_allowed_after_interval(self):
        """Email should be allowed after min_interval has passed."""
        throttler = EmailThrottler(min_interval=0.1)  # 100ms for testing

        # First email
        assert throttler.should_send("UC1:ANOMALY") is True

        # Immediate retry blocked
        assert throttler.should_send("UC1:ANOMALY") is False

        # Wait for interval to pass
        time.sleep(0.15)

        # Should now be allowed
        assert throttler.should_send("UC1:ANOMALY") is True

    def test_zero_interval_allows_all(self):
        """Zero interval should effectively disable throttling."""
        throttler = EmailThrottler(min_interval=0.0)

        assert throttler.should_send("UC1:ANOMALY") is True
        assert throttler.should_send("UC1:ANOMALY") is True
        assert throttler.should_send("UC1:ANOMALY") is True
