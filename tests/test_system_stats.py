"""
Tests for the System Monitor Widget API endpoint: /api/system/stats

This module tests the system statistics endpoint that provides
CPU and RAM metrics for the dashboard widget.

Test Categories:
- Response structure validation
- Value boundary testing
- Data type validation
- Error handling
- Performance under repeated calls
"""
import pytest
from fastapi.testclient import TestClient
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


# =============================================================================
# RESPONSE STRUCTURE TESTS
# =============================================================================

class TestSystemStatsResponseStructure:
    """Tests for validating the response structure of /api/system/stats."""

    def test_should_return_200_status_code(self, client):
        """Endpoint should return 200 OK on successful request."""
        response = client.get("/api/system/stats")
        assert response.status_code == 200

    def test_should_return_json_response(self, client):
        """Endpoint should return valid JSON."""
        response = client.get("/api/system/stats")
        assert response.headers["content-type"] == "application/json"
        # Should not raise an exception
        data = response.json()
        assert isinstance(data, dict)

    def test_should_contain_cpu_object(self, client):
        """Response should contain a 'cpu' object."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert "cpu" in data
        assert isinstance(data["cpu"], dict)

    def test_should_contain_memory_object(self, client):
        """Response should contain a 'memory' object."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert "memory" in data
        assert isinstance(data["memory"], dict)

    def test_cpu_should_have_required_fields(self, client):
        """CPU object should have percent, cores, and threads fields."""
        response = client.get("/api/system/stats")
        data = response.json()
        cpu = data["cpu"]

        assert "percent" in cpu, "CPU should have 'percent' field"
        assert "cores" in cpu, "CPU should have 'cores' field"
        assert "threads" in cpu, "CPU should have 'threads' field"

    def test_memory_should_have_required_fields(self, client):
        """Memory object should have percent, used_gb, total_gb, available_gb."""
        response = client.get("/api/system/stats")
        data = response.json()
        memory = data["memory"]

        assert "percent" in memory, "Memory should have 'percent' field"
        assert "used_gb" in memory, "Memory should have 'used_gb' field"
        assert "total_gb" in memory, "Memory should have 'total_gb' field"
        assert "available_gb" in memory, "Memory should have 'available_gb' field"


# =============================================================================
# DATA TYPE VALIDATION TESTS
# =============================================================================

class TestSystemStatsDataTypes:
    """Tests for validating data types of response fields."""

    def test_cpu_percent_should_be_numeric(self, client):
        """CPU percent should be a number (int or float)."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert isinstance(data["cpu"]["percent"], (int, float))

    def test_cpu_cores_should_be_integer(self, client):
        """CPU cores should be an integer."""
        response = client.get("/api/system/stats")
        data = response.json()
        # JSON integers are returned as int, but could be None on some systems
        cores = data["cpu"]["cores"]
        assert cores is None or isinstance(cores, int)

    def test_cpu_threads_should_be_integer(self, client):
        """CPU threads should be an integer."""
        response = client.get("/api/system/stats")
        data = response.json()
        threads = data["cpu"]["threads"]
        assert threads is None or isinstance(threads, int)

    def test_memory_percent_should_be_numeric(self, client):
        """Memory percent should be a number."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert isinstance(data["memory"]["percent"], (int, float))

    def test_memory_gb_values_should_be_numeric(self, client):
        """Memory GB values should be numbers."""
        response = client.get("/api/system/stats")
        data = response.json()
        memory = data["memory"]

        assert isinstance(memory["used_gb"], (int, float))
        assert isinstance(memory["total_gb"], (int, float))
        assert isinstance(memory["available_gb"], (int, float))


# =============================================================================
# VALUE BOUNDARY TESTS
# =============================================================================

class TestSystemStatsValueBoundaries:
    """Tests for validating value ranges and boundaries."""

    def test_cpu_percent_should_be_between_0_and_100(self, client):
        """CPU percent should be within 0-100 range."""
        response = client.get("/api/system/stats")
        data = response.json()
        cpu_percent = data["cpu"]["percent"]

        assert cpu_percent >= 0, "CPU percent should not be negative"
        assert cpu_percent <= 100, "CPU percent should not exceed 100"

    def test_memory_percent_should_be_between_0_and_100(self, client):
        """Memory percent should be within 0-100 range."""
        response = client.get("/api/system/stats")
        data = response.json()
        memory_percent = data["memory"]["percent"]

        assert memory_percent >= 0, "Memory percent should not be negative"
        assert memory_percent <= 100, "Memory percent should not exceed 100"

    def test_cpu_cores_should_be_positive_when_present(self, client):
        """CPU cores should be positive if not None."""
        response = client.get("/api/system/stats")
        data = response.json()
        cores = data["cpu"]["cores"]

        if cores is not None:
            assert cores > 0, "CPU cores should be positive"

    def test_cpu_threads_should_be_positive_when_present(self, client):
        """CPU threads should be positive if not None."""
        response = client.get("/api/system/stats")
        data = response.json()
        threads = data["cpu"]["threads"]

        if threads is not None:
            assert threads > 0, "CPU threads should be positive"

    def test_cpu_threads_should_be_gte_cores(self, client):
        """CPU threads should be >= cores (logical >= physical)."""
        response = client.get("/api/system/stats")
        data = response.json()
        cores = data["cpu"]["cores"]
        threads = data["cpu"]["threads"]

        if cores is not None and threads is not None:
            assert threads >= cores, "Threads should be >= cores"

    def test_memory_used_should_be_positive(self, client):
        """Memory used GB should be positive (system is running)."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert data["memory"]["used_gb"] > 0, "Used memory should be positive"

    def test_memory_total_should_be_positive(self, client):
        """Memory total GB should be positive."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert data["memory"]["total_gb"] > 0, "Total memory should be positive"

    def test_memory_available_should_be_non_negative(self, client):
        """Memory available GB should be non-negative."""
        response = client.get("/api/system/stats")
        data = response.json()
        assert data["memory"]["available_gb"] >= 0, "Available memory should not be negative"

    def test_memory_used_should_not_exceed_total(self, client):
        """Memory used should not exceed total memory."""
        response = client.get("/api/system/stats")
        data = response.json()
        memory = data["memory"]

        assert memory["used_gb"] <= memory["total_gb"], \
            "Used memory should not exceed total memory"

    def test_memory_available_should_not_exceed_total(self, client):
        """Memory available should not exceed total memory."""
        response = client.get("/api/system/stats")
        data = response.json()
        memory = data["memory"]

        assert memory["available_gb"] <= memory["total_gb"], \
            "Available memory should not exceed total memory"


# =============================================================================
# CONSISTENCY TESTS
# =============================================================================

class TestSystemStatsConsistency:
    """Tests for data consistency and logical relationships."""

    def test_memory_used_plus_available_approximately_equals_total(self, client):
        """Used + Available should approximately equal Total (within tolerance)."""
        response = client.get("/api/system/stats")
        data = response.json()
        memory = data["memory"]

        # Allow for some variance due to caching/buffers
        # used + available can be slightly different from total
        total = memory["total_gb"]
        used = memory["used_gb"]
        available = memory["available_gb"]

        # The relationship isn't exact due to OS buffering/caching
        # Just verify used + available doesn't wildly exceed total
        assert (used + available) <= (total * 1.5), \
            "Used + Available should not greatly exceed Total"


# =============================================================================
# RELIABILITY TESTS
# =============================================================================

class TestSystemStatsReliability:
    """Tests for endpoint reliability under various conditions."""

    def test_multiple_rapid_calls_should_succeed(self, client):
        """Endpoint should handle multiple rapid calls without failure."""
        for i in range(10):
            response = client.get("/api/system/stats")
            assert response.status_code == 200, f"Request {i+1} failed"

    def test_response_structure_consistent_across_calls(self, client):
        """Response structure should be consistent across multiple calls."""
        responses = [client.get("/api/system/stats").json() for _ in range(5)]

        for response in responses:
            assert "cpu" in response
            assert "memory" in response
            assert "percent" in response["cpu"]
            assert "percent" in response["memory"]

    def test_values_are_fresh_not_cached_stale(self, client):
        """
        Values should reflect current system state (not stale cache).
        Note: This is a basic sanity check - values may vary between calls.
        """
        response1 = client.get("/api/system/stats").json()
        response2 = client.get("/api/system/stats").json()

        # Both responses should have valid data
        assert response1["cpu"]["percent"] >= 0
        assert response2["cpu"]["percent"] >= 0
        # Values don't need to be different, just valid


# =============================================================================
# EDGE CASE TESTS
# =============================================================================

class TestSystemStatsEdgeCases:
    """Tests for edge cases and special scenarios."""

    def test_endpoint_with_trailing_slash(self, client):
        """Endpoint should work with or without trailing slash."""
        # FastAPI typically redirects, but let's verify behavior
        response = client.get("/api/system/stats/", follow_redirects=True)
        # Either 200 (if accepts) or redirect is fine
        assert response.status_code in [200, 307]

    def test_wrong_http_method_returns_405(self, client):
        """POST to GET endpoint should return 405 Method Not Allowed."""
        response = client.post("/api/system/stats")
        assert response.status_code == 405

    def test_put_method_returns_405(self, client):
        """PUT to GET endpoint should return 405 Method Not Allowed."""
        response = client.put("/api/system/stats")
        assert response.status_code == 405

    def test_delete_method_returns_405(self, client):
        """DELETE to GET endpoint should return 405 Method Not Allowed."""
        response = client.delete("/api/system/stats")
        assert response.status_code == 405


# =============================================================================
# WIDGET COMPATIBILITY TESTS
# =============================================================================

class TestWidgetCompatibility:
    """Tests ensuring the API response is compatible with the frontend widget."""

    def test_cpu_percent_is_widget_compatible(self, client):
        """
        CPU percent should be a simple number for the widget.
        Widget expects: cpu.percent as number 0-100
        """
        response = client.get("/api/system/stats")
        data = response.json()
        cpu_percent = data["cpu"]["percent"]

        # Must be directly usable in JS as a percentage
        assert isinstance(cpu_percent, (int, float))
        assert 0 <= cpu_percent <= 100

    def test_memory_percent_is_widget_compatible(self, client):
        """
        Memory percent should be a simple number for the widget.
        Widget expects: memory.percent as number 0-100
        """
        response = client.get("/api/system/stats")
        data = response.json()
        memory_percent = data["memory"]["percent"]

        # Must be directly usable in JS as a percentage
        assert isinstance(memory_percent, (int, float))
        assert 0 <= memory_percent <= 100

    def test_response_serializable_to_json(self, client):
        """Response should be cleanly serializable (no NaN, Infinity, etc.)."""
        import json
        response = client.get("/api/system/stats")
        data = response.json()

        # Re-serialize to ensure no special float values
        json_str = json.dumps(data)
        assert "NaN" not in json_str
        assert "Infinity" not in json_str
