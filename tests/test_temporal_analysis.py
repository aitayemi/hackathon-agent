"""
Tests for temporal analysis and multi-cycle history learning features.
"""
import pytest
from collections import deque
from datetime import datetime, timezone
from unittest.mock import Mock

from agent.analyzer import Analyzer
from agent.collector import EventCollector
from agent.config import AgentConfig


@pytest.fixture
def mock_collector():
    """Create a mock EventCollector."""
    collector = Mock(spec=EventCollector)
    collector.sources = []
    return collector


@pytest.fixture
def analyzer(mock_collector, monkeypatch):
    """Create an Analyzer instance with mocked collector."""
    # Mock boto3 client to avoid AWS credential issues in tests
    mock_bedrock_client = Mock()
    mock_boto3 = Mock()
    mock_boto3.client.return_value = mock_bedrock_client
    monkeypatch.setattr("agent.analyzer.boto3", mock_boto3)

    return Analyzer(mock_collector)


def create_mock_result(cycle: int, uc1_status: str, uc1_conf: float,
                       uc2_status: str, uc2_conf: float) -> dict:
    """Helper to create mock analysis results."""
    return {
        "cycle": cycle,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uc1": {
            "status": uc1_status,
            "confidence": uc1_conf,
            "evidence": ["test evidence"],
            "action": "test action"
        },
        "uc2": {
            "status": uc2_status,
            "confidence": uc2_conf,
            "evidence": ["test evidence"],
            "action": "test action"
        }
    }


class TestTemporalWindow:
    """Test temporal window configuration and history storage."""

    def test_max_history_calculated_from_config(self, mock_collector, monkeypatch):
        """Test that max_history is calculated based on temporal_window_hours."""
        # Mock boto3 client
        mock_bedrock_client = Mock()
        mock_boto3 = Mock()
        mock_boto3.client.return_value = mock_bedrock_client
        monkeypatch.setattr("agent.analyzer.boto3", mock_boto3)

        # Default: 6 hours * 3600 / 30 seconds = 720 cycles
        analyzer = Analyzer(mock_collector)
        assert analyzer.max_history >= 720
        assert analyzer.max_history >= 50  # Minimum safety threshold

    def test_history_deque_max_length(self, analyzer):
        """Test that result_history respects maxlen."""
        # Fill beyond max
        for i in range(analyzer.max_history + 100):
            analyzer.result_history.append({"cycle": i})

        # Should only keep max_history items
        assert len(analyzer.result_history) == analyzer.max_history
        # Should keep most recent
        assert analyzer.result_history[-1]["cycle"] == analyzer.max_history + 99


class TestTemporalTrendSummary:
    """Test temporal trend analysis calculations."""

    def test_empty_history_returns_empty_trends(self, analyzer):
        """Test that empty history returns empty trends dict."""
        trends = analyzer._build_temporal_trend_summary()
        assert trends == {}

    def test_single_result_trend_analysis(self, analyzer):
        """Test trend analysis with single result."""
        analyzer.result_history.append(
            create_mock_result(1, "ANOMALY_DETECTED", 0.85, "NORMAL", 0.95)
        )

        trends = analyzer._build_temporal_trend_summary()

        assert "uc1" in trends
        assert "uc2" in trends

        # Should have entries for available windows
        uc1_trends = trends["uc1"]
        assert "10min" in uc1_trends
        assert uc1_trends["10min"]["total_cycles"] == 1
        assert uc1_trends["10min"]["anomaly_count"] == 1
        assert uc1_trends["10min"]["anomaly_rate"] == 1.0

    def test_multiple_results_anomaly_rate_calculation(self, analyzer):
        """Test anomaly rate calculation over multiple cycles."""
        # Add 10 cycles: 7 anomalies, 3 normal
        for i in range(10):
            status = "ANOMALY_DETECTED" if i < 7 else "NORMAL"
            analyzer.result_history.append(
                create_mock_result(i, status, 0.75, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        uc1_trends = trends["uc1"]["10min"]

        assert uc1_trends["total_cycles"] == 10
        assert uc1_trends["anomaly_count"] == 7
        assert uc1_trends["anomaly_rate"] == 0.7

    def test_confidence_trend_rising(self, analyzer):
        """Test detection of rising confidence trend."""
        # Add results with rising confidence: 0.50 -> 0.75
        # Need more data points to establish clear trend
        confidences = [0.50, 0.52, 0.54, 0.56, 0.58] + [0.60, 0.63, 0.66, 0.69, 0.72, 0.75]
        for i, conf in enumerate(confidences):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", conf, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        uc1_trend = trends["uc1"]["10min"]["trend"]

        # Should detect rising trend (0.50 avg -> 0.72 avg = +0.22 > 0.05 threshold)
        assert uc1_trend == "rising"

    def test_confidence_trend_falling(self, analyzer):
        """Test detection of falling confidence trend."""
        # Add results with falling confidence: 0.90 -> 0.65
        # Need more data points to establish clear trend
        confidences = [0.90, 0.88, 0.86, 0.84, 0.82] + [0.80, 0.77, 0.74, 0.71, 0.68, 0.65]
        for i, conf in enumerate(confidences):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", conf, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        uc1_trend = trends["uc1"]["10min"]["trend"]

        # Should detect falling trend (0.88 avg -> 0.68 avg = -0.20 > 0.05 threshold)
        assert uc1_trend == "falling"

    def test_confidence_trend_stable(self, analyzer):
        """Test detection of stable confidence trend."""
        # Add results with stable confidence: ~0.75
        confidences = [0.74, 0.75, 0.76, 0.75, 0.74, 0.76]
        for i, conf in enumerate(confidences):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", conf, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        uc1_trend = trends["uc1"]["10min"]["trend"]

        # Should detect stable trend (variance < 0.05)
        assert uc1_trend == "stable"

    def test_multi_window_analysis(self, analyzer):
        """Test that multiple time windows are analyzed correctly."""
        # Add 150 cycles (75 minutes at 30s intervals)
        for i in range(150):
            # First 100 are anomalies, last 50 are normal
            status = "ANOMALY_DETECTED" if i < 100 else "NORMAL"
            analyzer.result_history.append(
                create_mock_result(i, status, 0.80, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        uc1_trends = trends["uc1"]

        # 10min window (last 20 cycles) should be all normal
        assert uc1_trends["10min"]["anomaly_rate"] == 0.0

        # 30min window (last 60 cycles) should be partial
        assert 0.0 < uc1_trends["30min"]["anomaly_rate"] < 1.0

        # 1hour+ windows should show higher anomaly rates
        assert uc1_trends["1hour"]["anomaly_rate"] > uc1_trends["30min"]["anomaly_rate"]

    def test_average_confidence_calculation(self, analyzer):
        """Test average confidence calculation."""
        confidences = [0.50, 0.60, 0.70, 0.80, 0.90]
        for i, conf in enumerate(confidences):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", conf, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        avg_conf = trends["uc1"]["10min"]["avg_confidence"]

        expected_avg = sum(confidences) / len(confidences)
        assert abs(avg_conf - expected_avg) < 0.01

    def test_latest_confidence_captured(self, analyzer):
        """Test that latest confidence is correctly captured."""
        confidences = [0.50, 0.60, 0.70, 0.80, 0.90]
        for i, conf in enumerate(confidences):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", conf, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()
        latest_conf = trends["uc1"]["10min"]["latest_confidence"]

        assert latest_conf == 0.90  # Last confidence


class TestPromptBuilding:
    """Test enhanced prompt building with temporal context."""

    def test_prompt_includes_temporal_section_with_history(self, analyzer):
        """Test that prompt includes temporal analysis section when history exists."""
        # Add some history
        for i in range(10):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", 0.75, "NORMAL", 0.95)
            )

        prompt = analyzer._build_prompt("test event summary")

        assert "TEMPORAL ANALYSIS CONTEXT" in prompt
        assert "Recent Analysis History" in prompt
        assert "Temporal Trends" in prompt
        assert "ANALYSIS INSTRUCTIONS" in prompt

    def test_prompt_without_history(self, analyzer):
        """Test that prompt works without history."""
        prompt = analyzer._build_prompt("test event summary")

        # Should still have event summary
        assert "test event summary" in prompt
        # Should not crash even without temporal section
        assert isinstance(prompt, str)

    def test_prompt_includes_recent_10_cycles(self, analyzer):
        """Test that prompt includes table of last 10 cycles."""
        # Add 15 cycles
        for i in range(15):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", 0.75, "NORMAL", 0.95)
            )

        prompt = analyzer._build_prompt("test events")

        # Should show last 10 cycles (5-14)
        for cycle_num in range(5, 15):
            assert f"cycle {cycle_num}" in prompt.lower() or str(cycle_num) in prompt

    def test_prompt_includes_trend_analysis(self, analyzer):
        """Test that prompt includes multi-window trend analysis."""
        # Add enough history for multiple windows
        for i in range(100):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", 0.75, "NORMAL", 0.95)
            )

        prompt = analyzer._build_prompt("test events")

        # Should include different time windows
        assert "10min" in prompt
        assert "30min" in prompt
        assert "1hour" in prompt

        # Should include trend indicators
        assert "Trend:" in prompt

    def test_prompt_includes_previous_analysis_details(self, analyzer):
        """Test that prompt includes details of previous analysis."""
        # Set last_result
        analyzer.last_result = create_mock_result(
            5, "ANOMALY_DETECTED", 0.85, "NORMAL", 0.95
        )
        analyzer.analysis_count = 5

        # Add to history
        analyzer.result_history.append(analyzer.last_result)

        prompt = analyzer._build_prompt("test events")

        assert "Previous Analysis Details" in prompt
        assert "Cycle #5" in prompt
        assert "0.85" in prompt or "85" in prompt  # Confidence
        assert "ANOMALY_DETECTED" in prompt

    def test_prompt_includes_temporal_instructions(self, analyzer):
        """Test that prompt includes enhanced temporal reasoning instructions."""
        # Add history
        for i in range(10):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", 0.75, "NORMAL", 0.95)
            )

        prompt = analyzer._build_prompt("test events")

        # Should include key temporal reasoning instructions
        assert "Persistent Anomalies" in prompt
        assert "Escalating Situations" in prompt
        assert "Improving Situations" in prompt
        assert "Rate of Change" in prompt
        assert "Safe Range Criteria" in prompt


class TestTemporalLearning:
    """Test the learning aspects of temporal analysis."""

    def test_persistent_anomaly_detection(self, analyzer):
        """Test that system recognizes persistent anomalies."""
        # Simulate 120 cycles (1 hour) of consistent anomalies
        for i in range(120):
            analyzer.result_history.append(
                create_mock_result(i, "ANOMALY_DETECTED", 0.80, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()

        # All windows should show high anomaly rates
        for window in ["10min", "30min", "1hour"]:
            assert trends["uc1"][window]["anomaly_rate"] > 0.95

    def test_improving_situation_detection(self, analyzer):
        """Test detection of improving situations (anomaly resolving)."""
        # First 100 cycles: anomaly, last 20 cycles: normal
        for i in range(120):
            status = "ANOMALY_DETECTED" if i < 100 else "NORMAL"
            analyzer.result_history.append(
                create_mock_result(i, status, 0.70, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()

        # Recent window (10min) should show low/zero anomaly rate
        assert trends["uc1"]["10min"]["anomaly_rate"] < 0.2

        # Longer windows should show higher rates
        assert trends["uc1"]["1hour"]["anomaly_rate"] > 0.5

    def test_escalating_situation_detection(self, analyzer):
        """Test detection of escalating situations (worsening anomaly)."""
        # Start normal, gradually increase anomaly rate
        for i in range(120):
            # Last 20 cycles: 90% anomaly, 60-100: 60% anomaly, 0-60: 30% anomaly
            is_anomaly = (
                (i >= 100 and i % 10 < 9) or
                (60 <= i < 100 and i % 10 < 6) or
                (i < 60 and i % 10 < 3)
            )
            status = "ANOMALY_DETECTED" if is_anomaly else "NORMAL"
            analyzer.result_history.append(
                create_mock_result(i, status, 0.70, "NORMAL", 0.95)
            )

        trends = analyzer._build_temporal_trend_summary()

        # Recent window should have highest anomaly rate
        if "10min" in trends["uc1"] and "1hour" in trends["uc1"]:
            recent_rate = trends["uc1"]["10min"]["anomaly_rate"]
            historical_rate = trends["uc1"]["1hour"]["anomaly_rate"]

            # Escalating: recent should be higher than historical
            assert recent_rate > historical_rate


class TestConfigurationIntegration:
    """Test integration with configuration system."""

    def test_temporal_window_hours_used_in_calculation(self, mock_collector, monkeypatch):
        """Test that temporal_window_hours config is used to calculate max_history."""
        # Mock boto3 client
        mock_bedrock_client = Mock()
        mock_boto3 = Mock()
        mock_boto3.client.return_value = mock_bedrock_client
        monkeypatch.setattr("agent.analyzer.boto3", mock_boto3)

        # Mock config with custom temporal window
        mock_config = Mock()
        mock_config.temporal_window_hours = 12.0  # 12 hours instead of 6
        mock_config.analysis_interval = 30.0
        mock_config.bedrock_region = "us-west-2"
        mock_config.bedrock_model_id = "test-model"
        mock_config.bedrock_fallback_model_id = None

        monkeypatch.setattr("agent.analyzer.config", mock_config)

        analyzer = Analyzer(mock_collector)

        # 12 hours * 3600 / 30 = 1440 cycles
        assert analyzer.max_history >= 1440

    def test_minimum_history_enforced(self, mock_collector, monkeypatch):
        """Test that minimum history of 50 cycles is enforced."""
        # Mock boto3 client
        mock_bedrock_client = Mock()
        mock_boto3 = Mock()
        mock_boto3.client.return_value = mock_bedrock_client
        monkeypatch.setattr("agent.analyzer.boto3", mock_boto3)

        # Mock config with very short temporal window
        mock_config = Mock()
        mock_config.temporal_window_hours = 0.1  # 6 minutes
        mock_config.analysis_interval = 30.0
        mock_config.bedrock_region = "us-west-2"
        mock_config.bedrock_model_id = "test-model"
        mock_config.bedrock_fallback_model_id = None

        monkeypatch.setattr("agent.analyzer.config", mock_config)

        analyzer = Analyzer(mock_collector)

        # Should enforce minimum of 50
        assert analyzer.max_history >= 50


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
