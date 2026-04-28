# Testing Guide

## Installation

Install the package with dev dependencies:

```bash
pip install -e ".[dev]"
```

## Running Tests

Run all tests:

```bash
pytest
```

Run with coverage report:

```bash
pytest --cov=agent --cov-report=term-missing
```

Run specific test file:

```bash
pytest tests/test_analyzer.py
```

Run specific test:

```bash
pytest tests/test_analyzer.py::TestHighPriorityDetection::test_low_capacity_is_high_priority
```

Run tests matching a pattern:

```bash
pytest -k "high_priority"
```

## Test Structure

- `tests/test_analyzer.py` - Tests for anomaly detection logic
- `tests/test_collector.py` - Tests for event collection and deduplication
- `tests/test_config.py` - Tests for configuration validation
- `tests/test_notifier.py` - Tests for email throttling

## Writing Tests

Follow the existing patterns:

```python
class TestFeatureName:
    """Test description."""
    
    def test_specific_behavior(self):
        """Test specific behavior description."""
        # Arrange
        input_data = {...}
        
        # Act
        result = function_under_test(input_data)
        
        # Assert
        assert result == expected_value
```

## CI Integration

Add to GitHub Actions workflow:

```yaml
- name: Run tests
  run: |
    pip install -e ".[dev]"
    pytest --cov=agent --cov-report=xml
```
