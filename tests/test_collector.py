"""Tests for collector module."""
import pytest
from collections import deque
from agent.collector import EventCollector, SourceState


class TestEventDeduplication:
    """Test event deduplication logic."""

    def test_generate_event_id_with_id_field(self):
        """Events with 'id' field should use it."""
        collector = EventCollector()
        src = SourceState(
            use_case="UC1",
            name="test-source",
            base_url="http://test",
        )
        evt = {"id": "evt-123", "data": {"foo": "bar"}}

        event_id = collector._generate_event_id(evt, src)
        assert event_id == "UC1/test-source/evt-123"

    def test_generate_event_id_without_id_field(self):
        """Events without 'id' should generate fingerprint."""
        collector = EventCollector()
        src = SourceState(
            use_case="UC1",
            name="test-source",
            base_url="http://test",
        )
        evt = {
            "timestamp": 1234567890.5,
            "data": {"capacity_pct": 29, "supplier": "CoreFab"}
        }

        event_id = collector._generate_event_id(evt, src)
        assert "UC1/test-source" in event_id
        assert "1234567890.5" in event_id
        assert "capacity_pct:29" in event_id

    def test_different_events_get_different_ids(self):
        """Two different events should get different IDs."""
        collector = EventCollector()
        src = SourceState(
            use_case="UC1",
            name="test-source",
            base_url="http://test",
        )

        evt1 = {"timestamp": 1000, "data": {"value": 10}}
        evt2 = {"timestamp": 2000, "data": {"value": 20}}

        id1 = collector._generate_event_id(evt1, src)
        id2 = collector._generate_event_id(evt2, src)

        assert id1 != id2

    def test_same_event_gets_same_id(self):
        """The same event should consistently get the same ID."""
        collector = EventCollector()
        src = SourceState(
            use_case="UC1",
            name="test-source",
            base_url="http://test",
        )

        evt = {"timestamp": 1000, "data": {"value": 10}}

        id1 = collector._generate_event_id(evt, src)
        id2 = collector._generate_event_id(evt, src)

        assert id1 == id2


class TestCollectorInit:
    """Test collector initialization."""

    def test_collector_creates_all_sources(self):
        """Collector should create 8 sources (4 UC1 + 4 UC2)."""
        collector = EventCollector()
        assert len(collector.sources) == 8

        uc1_sources = [s for s in collector.sources if s.use_case == "UC1"]
        uc2_sources = [s for s in collector.sources if s.use_case == "UC2"]

        assert len(uc1_sources) == 4
        assert len(uc2_sources) == 4

    def test_source_names_are_correct(self):
        """Verify source names match expected UC1/UC2 sources."""
        collector = EventCollector()

        uc1_names = {s.name for s in collector.sources if s.use_case == "UC1"}
        assert uc1_names == {
            "supplier-capacity",
            "logistics",
            "geopolitical",
            "inventory",
        }

        uc2_names = {s.name for s in collector.sources if s.use_case == "UC2"}
        assert uc2_names == {
            "submission-queue",
            "policy-kb",
            "submission-history",
            "escalation-queue",
        }
