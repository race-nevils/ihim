"""
Tests for the Stopwatch API Endpoints

This module tests the Stopwatch functionality in the iHIM Command Center.
The feature allows users to spawn multiple independent stopwatches that can be
started, stopped, reset, and deleted independently.

Test Categories:
1. Response Structure Tests
2. CRUD Operations Tests
3. Start/Stop/Reset Tests
4. Lap Time Tests
5. Multiple Stopwatch Tests
6. Edge Cases and Boundary Tests
7. Persistence Tests
8. Error Handling Tests
"""
import pytest
from fastapi.testclient import TestClient
import sys
import json
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app, STOPWATCHES_FILE, save_stopwatches, load_stopwatches


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_stopwatches():
    """Clean up stopwatches file before and after each test."""
    # Setup: Clear stopwatches
    save_stopwatches([])
    yield
    # Teardown: Clear stopwatches
    save_stopwatches([])


# =============================================================================
# RESPONSE STRUCTURE TESTS
# =============================================================================

class TestStopwatchesResponseStructure:
    """Tests for validating the response structure of /api/stopwatches endpoints."""

    def test_get_stopwatches_should_return_200_status_code(self, client):
        """GET /api/stopwatches should return 200 OK."""
        response = client.get("/api/stopwatches")
        assert response.status_code == 200

    def test_get_stopwatches_should_return_json_response(self, client):
        """GET /api/stopwatches should return valid JSON."""
        response = client.get("/api/stopwatches")
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert isinstance(data, dict)

    def test_get_stopwatches_should_contain_stopwatches_array(self, client):
        """Response should contain a 'stopwatches' array."""
        response = client.get("/api/stopwatches")
        data = response.json()
        assert "stopwatches" in data
        assert isinstance(data["stopwatches"], list)

    def test_get_stopwatches_should_return_empty_array_when_none_exist(self, client):
        """Response should contain empty array when no stopwatches exist."""
        response = client.get("/api/stopwatches")
        data = response.json()
        assert data["stopwatches"] == []

    def test_create_stopwatch_should_return_201_status_code(self, client):
        """POST /api/stopwatches should return 201 Created."""
        response = client.post("/api/stopwatches")
        assert response.status_code == 201

    def test_create_stopwatch_should_return_success_and_stopwatch(self, client):
        """POST /api/stopwatches should return success flag and created stopwatch."""
        response = client.post("/api/stopwatches")
        data = response.json()
        assert data["success"] is True
        assert "stopwatch" in data
        assert isinstance(data["stopwatch"], dict)

    def test_stopwatch_should_have_required_fields(self, client):
        """Created stopwatch should have id, label, elapsed_ms, is_running, started_at, created_at."""
        response = client.post("/api/stopwatches")
        stopwatch = response.json()["stopwatch"]

        assert "id" in stopwatch, "Stopwatch should have 'id' field"
        assert "label" in stopwatch, "Stopwatch should have 'label' field"
        assert "elapsed_ms" in stopwatch, "Stopwatch should have 'elapsed_ms' field"
        assert "is_running" in stopwatch, "Stopwatch should have 'is_running' field"
        assert "started_at" in stopwatch, "Stopwatch should have 'started_at' field"
        assert "created_at" in stopwatch, "Stopwatch should have 'created_at' field"

    def test_stopwatch_should_have_correct_initial_state(self, client):
        """Created stopwatch should start in stopped state with 0 elapsed time."""
        response = client.post("/api/stopwatches")
        stopwatch = response.json()["stopwatch"]

        assert stopwatch["elapsed_ms"] == 0
        assert stopwatch["is_running"] is False
        assert stopwatch["started_at"] is None


# =============================================================================
# CRUD OPERATIONS TESTS
# =============================================================================

class TestStopwatchesCRUDOperations:
    """Tests for Create, Read, Update, Delete operations."""

    # CREATE TESTS
    def test_should_create_stopwatch_without_label(self, client):
        """Should create stopwatch without specifying a label."""
        response = client.post("/api/stopwatches")
        data = response.json()
        assert data["success"] is True
        assert data["stopwatch"]["label"] == ""

    def test_should_create_stopwatch_with_label(self, client):
        """Should create stopwatch with specified label."""
        response = client.post("/api/stopwatches", json={"label": "Workout Timer"})
        data = response.json()
        assert data["success"] is True
        assert data["stopwatch"]["label"] == "Workout Timer"

    def test_should_generate_unique_id_for_each_stopwatch(self, client):
        """Each stopwatch should have a unique ID."""
        response1 = client.post("/api/stopwatches")
        response2 = client.post("/api/stopwatches")
        response3 = client.post("/api/stopwatches")

        id1 = response1.json()["stopwatch"]["id"]
        id2 = response2.json()["stopwatch"]["id"]
        id3 = response3.json()["stopwatch"]["id"]

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3

    # READ TESTS
    def test_should_return_all_stopwatches(self, client):
        """Should return all created stopwatches."""
        client.post("/api/stopwatches", json={"label": "Timer 1"})
        client.post("/api/stopwatches", json={"label": "Timer 2"})
        client.post("/api/stopwatches", json={"label": "Timer 3"})

        response = client.get("/api/stopwatches")
        stopwatches = response.json()["stopwatches"]

        assert len(stopwatches) == 3

    def test_should_get_single_stopwatch_by_id(self, client):
        """Should retrieve a single stopwatch by ID."""
        create_response = client.post("/api/stopwatches", json={"label": "My Timer"})
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        response = client.get(f"/api/stopwatches/{stopwatch_id}")
        data = response.json()

        assert data["success"] is True
        assert data["stopwatch"]["id"] == stopwatch_id
        assert data["stopwatch"]["label"] == "My Timer"

    # UPDATE TESTS
    def test_should_update_stopwatch_label(self, client):
        """Should update stopwatch label."""
        create_response = client.post("/api/stopwatches", json={"label": "Original"})
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        response = client.put(f"/api/stopwatches/{stopwatch_id}", json={"label": "Updated"})
        data = response.json()

        assert data["success"] is True
        assert data["stopwatch"]["label"] == "Updated"

    # DELETE TESTS
    def test_should_delete_stopwatch_by_id(self, client):
        """Should delete a stopwatch by ID."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        response = client.delete(f"/api/stopwatches/{stopwatch_id}")
        assert response.json()["success"] is True

        # Verify it's gone
        get_response = client.get("/api/stopwatches")
        stopwatches = get_response.json()["stopwatches"]
        stopwatch_ids = [sw["id"] for sw in stopwatches]
        assert stopwatch_id not in stopwatch_ids

    def test_should_delete_all_stopwatches(self, client):
        """Should delete all stopwatches."""
        client.post("/api/stopwatches")
        client.post("/api/stopwatches")
        client.post("/api/stopwatches")

        response = client.delete("/api/stopwatches")
        assert response.json()["success"] is True

        # Verify all are gone
        get_response = client.get("/api/stopwatches")
        assert get_response.json()["stopwatches"] == []


# =============================================================================
# START/STOP/RESET TESTS
# =============================================================================

class TestStopwatchStartStopReset:
    """Tests for start, stop, and reset operations."""

    def test_should_start_stopwatch(self, client):
        """Should start a stopped stopwatch."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        response = client.post(f"/api/stopwatches/{stopwatch_id}/start")
        data = response.json()

        assert data["success"] is True
        assert data["stopwatch"]["is_running"] is True
        assert data["stopwatch"]["started_at"] is not None

    def test_should_stop_running_stopwatch(self, client):
        """Should stop a running stopwatch."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Start it
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        # Wait a tiny bit
        time.sleep(0.01)
        # Stop it
        response = client.post(f"/api/stopwatches/{stopwatch_id}/stop")
        data = response.json()

        assert data["success"] is True
        assert data["stopwatch"]["is_running"] is False
        assert data["stopwatch"]["started_at"] is None
        assert data["stopwatch"]["elapsed_ms"] >= 0

    def test_should_accumulate_elapsed_time_across_starts_and_stops(self, client):
        """Elapsed time should accumulate when starting and stopping multiple times."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # First run
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.02)
        client.post(f"/api/stopwatches/{stopwatch_id}/stop")

        # Get first elapsed
        get_response = client.get(f"/api/stopwatches/{stopwatch_id}")
        first_elapsed = get_response.json()["stopwatch"]["elapsed_ms"]

        # Second run
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.02)
        stop_response = client.post(f"/api/stopwatches/{stopwatch_id}/stop")

        second_elapsed = stop_response.json()["stopwatch"]["elapsed_ms"]

        assert second_elapsed >= first_elapsed

    def test_should_reset_stopwatch_to_zero(self, client):
        """Should reset elapsed time to 0."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Run for a bit
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.01)
        client.post(f"/api/stopwatches/{stopwatch_id}/stop")

        # Reset
        response = client.post(f"/api/stopwatches/{stopwatch_id}/reset")
        data = response.json()

        assert data["success"] is True
        assert data["stopwatch"]["elapsed_ms"] == 0
        assert data["stopwatch"]["is_running"] is False
        assert data["stopwatch"]["started_at"] is None

    def test_should_reset_running_stopwatch(self, client):
        """Should stop and reset a running stopwatch."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Start it
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.01)

        # Reset while running
        response = client.post(f"/api/stopwatches/{stopwatch_id}/reset")
        data = response.json()

        assert data["stopwatch"]["elapsed_ms"] == 0
        assert data["stopwatch"]["is_running"] is False

    def test_should_be_idempotent_when_starting_already_running_stopwatch(self, client):
        """Starting an already running stopwatch should not error."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Start twice
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        response = client.post(f"/api/stopwatches/{stopwatch_id}/start")

        assert response.json()["success"] is True
        assert response.json()["stopwatch"]["is_running"] is True

    def test_should_be_idempotent_when_stopping_already_stopped_stopwatch(self, client):
        """Stopping an already stopped stopwatch should not error."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Stop without starting
        response = client.post(f"/api/stopwatches/{stopwatch_id}/stop")

        assert response.json()["success"] is True
        assert response.json()["stopwatch"]["is_running"] is False


# =============================================================================
# LAP TIME TESTS
# =============================================================================

class TestStopwatchLapTimes:
    """Tests for lap time functionality."""

    def test_should_record_lap_time_while_running(self, client):
        """Should record lap time without stopping the stopwatch."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Start and run for a bit
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.01)

        # Record lap
        response = client.post(f"/api/stopwatches/{stopwatch_id}/lap")
        data = response.json()

        assert data["success"] is True
        assert "lap_ms" in data
        assert data["lap_ms"] >= 0
        assert "timestamp" in data

    def test_should_record_lap_time_while_stopped(self, client):
        """Should record lap time when stopwatch is stopped."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Start, run, stop
        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.01)
        client.post(f"/api/stopwatches/{stopwatch_id}/stop")

        # Record lap while stopped
        response = client.post(f"/api/stopwatches/{stopwatch_id}/lap")
        data = response.json()

        assert data["success"] is True
        assert data["lap_ms"] >= 0

    def test_stopwatch_should_continue_running_after_lap(self, client):
        """Recording a lap should not stop the stopwatch."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Start
        client.post(f"/api/stopwatches/{stopwatch_id}/start")

        # Record lap
        client.post(f"/api/stopwatches/{stopwatch_id}/lap")

        # Verify still running
        get_response = client.get(f"/api/stopwatches/{stopwatch_id}")
        assert get_response.json()["stopwatch"]["is_running"] is True


# =============================================================================
# MULTIPLE STOPWATCH TESTS
# =============================================================================

class TestMultipleStopwatches:
    """Tests for multiple independent stopwatch operation."""

    def test_should_run_multiple_stopwatches_independently(self, client):
        """Multiple stopwatches should operate independently."""
        # Create 3 stopwatches
        r1 = client.post("/api/stopwatches", json={"label": "Timer 1"})
        r2 = client.post("/api/stopwatches", json={"label": "Timer 2"})
        r3 = client.post("/api/stopwatches", json={"label": "Timer 3"})

        id1 = r1.json()["stopwatch"]["id"]
        id2 = r2.json()["stopwatch"]["id"]
        id3 = r3.json()["stopwatch"]["id"]

        # Start only the first and third
        client.post(f"/api/stopwatches/{id1}/start")
        client.post(f"/api/stopwatches/{id3}/start")

        # Wait
        time.sleep(0.01)

        # Get all
        response = client.get("/api/stopwatches")
        stopwatches = response.json()["stopwatches"]

        sw1 = next(sw for sw in stopwatches if sw["id"] == id1)
        sw2 = next(sw for sw in stopwatches if sw["id"] == id2)
        sw3 = next(sw for sw in stopwatches if sw["id"] == id3)

        assert sw1["is_running"] is True
        assert sw2["is_running"] is False  # Never started
        assert sw3["is_running"] is True

    def test_should_stop_one_without_affecting_others(self, client):
        """Stopping one stopwatch should not affect others."""
        # Create 2 stopwatches
        r1 = client.post("/api/stopwatches")
        r2 = client.post("/api/stopwatches")

        id1 = r1.json()["stopwatch"]["id"]
        id2 = r2.json()["stopwatch"]["id"]

        # Start both
        client.post(f"/api/stopwatches/{id1}/start")
        client.post(f"/api/stopwatches/{id2}/start")

        # Stop only the first
        client.post(f"/api/stopwatches/{id1}/stop")

        # Check states
        get1 = client.get(f"/api/stopwatches/{id1}")
        get2 = client.get(f"/api/stopwatches/{id2}")

        assert get1.json()["stopwatch"]["is_running"] is False
        assert get2.json()["stopwatch"]["is_running"] is True

    def test_should_delete_one_without_affecting_others(self, client):
        """Deleting one stopwatch should not affect others."""
        # Create 3 stopwatches
        r1 = client.post("/api/stopwatches", json={"label": "Keep 1"})
        r2 = client.post("/api/stopwatches", json={"label": "Delete Me"})
        r3 = client.post("/api/stopwatches", json={"label": "Keep 2"})

        id1 = r1.json()["stopwatch"]["id"]
        id2 = r2.json()["stopwatch"]["id"]
        id3 = r3.json()["stopwatch"]["id"]

        # Delete the second
        client.delete(f"/api/stopwatches/{id2}")

        # Get all
        response = client.get("/api/stopwatches")
        stopwatches = response.json()["stopwatches"]
        ids = [sw["id"] for sw in stopwatches]

        assert id1 in ids
        assert id2 not in ids
        assert id3 in ids
        assert len(stopwatches) == 2

    def test_should_handle_many_stopwatches(self, client):
        """Should handle creation and management of many stopwatches."""
        stopwatch_ids = []

        # Create 20 stopwatches
        for i in range(20):
            response = client.post("/api/stopwatches", json={"label": f"Timer {i}"})
            assert response.status_code == 201
            stopwatch_ids.append(response.json()["stopwatch"]["id"])

        # Verify all exist
        response = client.get("/api/stopwatches")
        assert len(response.json()["stopwatches"]) == 20

        # Start every other one
        for i, sw_id in enumerate(stopwatch_ids):
            if i % 2 == 0:
                client.post(f"/api/stopwatches/{sw_id}/start")

        # Verify state
        response = client.get("/api/stopwatches")
        running_count = sum(1 for sw in response.json()["stopwatches"] if sw["is_running"])
        assert running_count == 10


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestStopwatchesEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_unicode_label(self, client):
        """Should handle unicode characters in label."""
        unicode_label = "Timer with emoji 🚀 and Japanese こんにちは"
        response = client.post("/api/stopwatches", json={"label": unicode_label})
        assert response.status_code == 201
        assert response.json()["stopwatch"]["label"] == unicode_label

    def test_should_handle_special_characters_in_label(self, client):
        """Should handle special characters in label."""
        special = '<script>alert("xss")</script> & "quotes" \'single\''
        response = client.post("/api/stopwatches", json={"label": special})
        assert response.status_code == 201
        assert response.json()["stopwatch"]["label"] == special

    def test_should_return_error_for_get_nonexistent_stopwatch(self, client):
        """Should return error when getting non-existent stopwatch."""
        response = client.get("/api/stopwatches/nonexistent123")
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    def test_should_return_error_for_update_nonexistent_stopwatch(self, client):
        """Should return error when updating non-existent stopwatch."""
        response = client.put("/api/stopwatches/nonexistent123", json={"label": "New"})
        data = response.json()
        assert data["success"] is False

    def test_should_return_error_for_start_nonexistent_stopwatch(self, client):
        """Should return error when starting non-existent stopwatch."""
        response = client.post("/api/stopwatches/nonexistent123/start")
        data = response.json()
        assert data["success"] is False

    def test_should_return_error_for_stop_nonexistent_stopwatch(self, client):
        """Should return error when stopping non-existent stopwatch."""
        response = client.post("/api/stopwatches/nonexistent123/stop")
        data = response.json()
        assert data["success"] is False

    def test_should_return_error_for_reset_nonexistent_stopwatch(self, client):
        """Should return error when resetting non-existent stopwatch."""
        response = client.post("/api/stopwatches/nonexistent123/reset")
        data = response.json()
        assert data["success"] is False

    def test_should_return_error_for_lap_nonexistent_stopwatch(self, client):
        """Should return error when recording lap for non-existent stopwatch."""
        response = client.post("/api/stopwatches/nonexistent123/lap")
        data = response.json()
        assert data["success"] is False

    def test_should_return_error_for_delete_nonexistent_stopwatch(self, client):
        """Should return error when deleting non-existent stopwatch."""
        response = client.delete("/api/stopwatches/nonexistent123")
        data = response.json()
        assert data["success"] is False

    def test_should_handle_empty_label(self, client):
        """Should handle empty string label."""
        response = client.post("/api/stopwatches", json={"label": ""})
        assert response.status_code == 201
        assert response.json()["stopwatch"]["label"] == ""

    def test_should_handle_null_label(self, client):
        """Should handle null label."""
        response = client.post("/api/stopwatches", json={"label": None})
        assert response.status_code == 201
        assert response.json()["stopwatch"]["label"] == ""

    def test_id_should_be_8_character_alphanumeric(self, client):
        """Stopwatch IDs should be 8 character alphanumeric strings."""
        response = client.post("/api/stopwatches")
        stopwatch_id = response.json()["stopwatch"]["id"]
        assert len(stopwatch_id) == 8

    def test_created_at_should_be_valid_iso_timestamp(self, client):
        """created_at should be a valid ISO timestamp."""
        response = client.post("/api/stopwatches")
        created_at = response.json()["stopwatch"]["created_at"]
        # Should end with Z (UTC)
        assert created_at.endswith("Z")
        # Should be parseable as ISO format
        from datetime import datetime
        # Remove the Z for parsing
        datetime.fromisoformat(created_at.rstrip("Z"))


# =============================================================================
# PERSISTENCE TESTS
# =============================================================================

class TestStopwatchesPersistence:
    """Tests for data persistence."""

    def test_stopwatches_should_persist_after_retrieval(self, client):
        """Stopwatches should persist and be retrievable."""
        create_response = client.post("/api/stopwatches", json={"label": "Persistent"})
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        # Retrieve multiple times
        for _ in range(3):
            response = client.get("/api/stopwatches")
            stopwatches = response.json()["stopwatches"]
            stopwatch_ids = [sw["id"] for sw in stopwatches]
            assert stopwatch_id in stopwatch_ids

    def test_stopwatches_file_should_be_valid_json(self, client):
        """Stopwatches file should contain valid JSON."""
        client.post("/api/stopwatches", json={"label": "Timer 1"})
        client.post("/api/stopwatches", json={"label": "Timer 2"})

        assert STOPWATCHES_FILE.exists()
        content = STOPWATCHES_FILE.read_text(encoding="utf-8")
        data = json.loads(content)  # Should not raise
        assert "stopwatches" in data
        assert len(data["stopwatches"]) == 2

    def test_elapsed_time_should_persist_after_stop(self, client):
        """Elapsed time should be saved after stopping."""
        create_response = client.post("/api/stopwatches")
        stopwatch_id = create_response.json()["stopwatch"]["id"]

        client.post(f"/api/stopwatches/{stopwatch_id}/start")
        time.sleep(0.02)
        client.post(f"/api/stopwatches/{stopwatch_id}/stop")

        # Get from API
        response = client.get(f"/api/stopwatches/{stopwatch_id}")
        api_elapsed = response.json()["stopwatch"]["elapsed_ms"]

        # Get from file
        stopwatches = load_stopwatches()
        file_sw = next(sw for sw in stopwatches if sw["id"] == stopwatch_id)
        file_elapsed = file_sw["elapsed_ms"]

        assert api_elapsed == file_elapsed
        assert api_elapsed >= 0


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestStopwatchesErrorHandling:
    """Tests for error handling scenarios."""

    def test_label_max_length_should_be_enforced(self, client):
        """Label longer than 100 characters should be rejected."""
        long_label = "x" * 101
        response = client.post("/api/stopwatches", json={"label": long_label})
        assert response.status_code == 422

    def test_label_at_max_length_should_be_accepted(self, client):
        """Label at exactly 100 characters should be accepted."""
        max_label = "x" * 100
        response = client.post("/api/stopwatches", json={"label": max_label})
        assert response.status_code == 201
        assert len(response.json()["stopwatch"]["label"]) == 100


# =============================================================================
# SECURITY TESTS
# =============================================================================

class TestStopwatchesSecurity:
    """Tests for security-related concerns."""

    def test_should_preserve_html_as_text(self, client):
        """HTML should be stored as text (not executed)."""
        html_content = '<script>alert("xss")</script>'
        response = client.post("/api/stopwatches", json={"label": html_content})
        assert response.status_code == 201
        assert response.json()["stopwatch"]["label"] == html_content

    def test_should_handle_sql_injection_attempts(self, client):
        """SQL injection attempts should be stored as text."""
        sql_injection = "'; DROP TABLE stopwatches; --"
        response = client.post("/api/stopwatches", json={"label": sql_injection})
        assert response.status_code == 201
        assert response.json()["stopwatch"]["label"] == sql_injection
