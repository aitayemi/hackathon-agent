"""Tests for analyzer module."""
import pytest
from agent.analyzer import _is_high_priority


class TestHighPriorityDetection:
    """Test the high-priority event detection logic."""

    def test_low_capacity_is_high_priority(self):
        """Events with capacity_pct < 50 should be high priority."""
        evt = {"data": {"capacity_pct": 29}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"capacity_pct": 75}}
        assert _is_high_priority(evt) is False

    def test_low_days_of_supply_is_high_priority(self):
        """Events with days_of_supply < 5 should be high priority."""
        evt = {"data": {"days_of_supply": 2}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"days_of_supply": 10}}
        assert _is_high_priority(evt) is False

    def test_critical_alert_is_high_priority(self):
        """Events with CRITICAL in alert field should be high priority."""
        evt = {"data": {"alert": "CRITICAL: Low inventory"}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"alert": "WARNING: Check status"}}
        assert _is_high_priority(evt) is False

    def test_high_delay_is_high_priority(self):
        """Events with delay_hours > 48 should be high priority."""
        evt = {"data": {"delay_hours": 72}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"delay_hours": 24}}
        assert _is_high_priority(evt) is False

    def test_critical_severity_is_high_priority(self):
        """Events with critical/high severity should be high priority."""
        evt = {"data": {"severity": "critical"}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"severity": "high"}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"severity": "medium"}}
        assert _is_high_priority(evt) is False

    def test_escalation_is_high_priority(self):
        """Events with escalation_reason should be high priority."""
        evt = {"data": {"escalation_reason": "prior violation pattern"}}
        assert _is_high_priority(evt) is True

    def test_rejection_is_high_priority(self):
        """Events with outcome=rejected should be high priority."""
        evt = {"data": {"outcome": "rejected"}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"outcome": "approved"}}
        assert _is_high_priority(evt) is False

    def test_suspicious_bundle_is_high_priority(self):
        """The com.obscure.tracker bundle should be high priority."""
        evt = {"data": {"bundle_id": "com.obscure.tracker"}}
        assert _is_high_priority(evt) is True

        evt = {"data": {"triggered_by": "com.obscure.tracker"}}
        assert _is_high_priority(evt) is True

    def test_normal_event_is_not_high_priority(self):
        """Normal events should not be high priority."""
        evt = {"data": {"capacity_pct": 85, "status": "normal"}}
        assert _is_high_priority(evt) is False

    def test_flat_event_structure(self):
        """Should handle flat event structure (no 'data' wrapper)."""
        evt = {"capacity_pct": 29}
        assert _is_high_priority(evt) is True

        evt = {"delay_hours": 72}
        assert _is_high_priority(evt) is True
