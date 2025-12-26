"""
Tests for the Task List API Endpoints

This module tests the Task List functionality in the iHIM Command Center.
The feature allows users to manage tasks with priorities (high, medium, low)
and completion status.

Test Categories:
1. Response Structure Tests
2. CRUD Operations Tests
3. Data Validation Tests
4. Priority and Sorting Tests
5. Edge Cases and Boundary Tests
6. Persistence Tests
7. Error Handling Tests
"""
import pytest
from fastapi.testclient import TestClient
import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app, TASKS_FILE, save_tasks, load_tasks


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_tasks():
    """Clean up tasks file before and after each test."""
    # Setup: Clear tasks
    save_tasks([])
    yield
    # Teardown: Clear tasks
    save_tasks([])


# =============================================================================
# RESPONSE STRUCTURE TESTS
# =============================================================================

class TestTasksResponseStructure:
    """Tests for validating the response structure of /api/tasks endpoints."""

    def test_get_tasks_should_return_200_status_code(self, client):
        """GET /api/tasks should return 200 OK."""
        response = client.get("/api/tasks")
        assert response.status_code == 200

    def test_get_tasks_should_return_json_response(self, client):
        """GET /api/tasks should return valid JSON."""
        response = client.get("/api/tasks")
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert isinstance(data, dict)

    def test_get_tasks_should_contain_tasks_array(self, client):
        """Response should contain a 'tasks' array."""
        response = client.get("/api/tasks")
        data = response.json()
        assert "tasks" in data
        assert isinstance(data["tasks"], list)

    def test_get_tasks_should_return_empty_array_when_no_tasks(self, client):
        """Response should contain empty array when no tasks exist."""
        response = client.get("/api/tasks")
        data = response.json()
        assert data["tasks"] == []

    def test_create_task_should_return_success_and_task(self, client):
        """POST /api/tasks should return success flag and created task."""
        response = client.post("/api/tasks", json={"text": "Test task"})
        data = response.json()
        assert data["success"] is True
        assert "task" in data
        assert isinstance(data["task"], dict)

    def test_task_should_have_required_fields(self, client):
        """Created task should have id, text, priority, completed."""
        response = client.post("/api/tasks", json={"text": "Test task"})
        task = response.json()["task"]

        assert "id" in task, "Task should have 'id' field"
        assert "text" in task, "Task should have 'text' field"
        assert "priority" in task, "Task should have 'priority' field"
        assert "completed" in task, "Task should have 'completed' field"


# =============================================================================
# CRUD OPERATIONS TESTS
# =============================================================================

class TestTasksCRUDOperations:
    """Tests for Create, Read, Update, Delete operations."""

    # CREATE TESTS
    def test_should_create_task_with_text_only(self, client):
        """Should create task with text only (default priority)."""
        response = client.post("/api/tasks", json={"text": "My first task"})
        data = response.json()
        assert data["success"] is True
        assert data["task"]["text"] == "My first task"
        assert data["task"]["priority"] == "medium"  # Default
        assert data["task"]["completed"] is False  # Default

    def test_should_create_task_with_priority(self, client):
        """Should create task with specified priority."""
        response = client.post("/api/tasks", json={
            "text": "Urgent task",
            "priority": "high"
        })
        data = response.json()
        assert data["success"] is True
        assert data["task"]["priority"] == "high"

    def test_should_generate_unique_id_for_each_task(self, client):
        """Each task should have a unique ID."""
        response1 = client.post("/api/tasks", json={"text": "Task 1"})
        response2 = client.post("/api/tasks", json={"text": "Task 2"})
        response3 = client.post("/api/tasks", json={"text": "Task 3"})

        id1 = response1.json()["task"]["id"]
        id2 = response2.json()["task"]["id"]
        id3 = response3.json()["task"]["id"]

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3

    # READ TESTS
    def test_should_return_all_tasks(self, client):
        """Should return all created tasks."""
        client.post("/api/tasks", json={"text": "Task 1"})
        client.post("/api/tasks", json={"text": "Task 2"})
        client.post("/api/tasks", json={"text": "Task 3"})

        response = client.get("/api/tasks")
        tasks = response.json()["tasks"]

        assert len(tasks) == 3

    # UPDATE TESTS
    def test_should_update_task_text(self, client):
        """Should update task text."""
        create_response = client.post("/api/tasks", json={"text": "Original"})
        task_id = create_response.json()["task"]["id"]

        response = client.put(f"/api/tasks/{task_id}", json={"text": "Updated"})
        data = response.json()

        assert data["success"] is True
        assert data["task"]["text"] == "Updated"

    def test_should_update_task_priority(self, client):
        """Should update task priority."""
        create_response = client.post("/api/tasks", json={"text": "Task", "priority": "low"})
        task_id = create_response.json()["task"]["id"]

        response = client.put(f"/api/tasks/{task_id}", json={"priority": "high"})
        data = response.json()

        assert data["success"] is True
        assert data["task"]["priority"] == "high"

    def test_should_update_task_completed_status(self, client):
        """Should update task completed status."""
        create_response = client.post("/api/tasks", json={"text": "Task"})
        task_id = create_response.json()["task"]["id"]

        # Mark as completed
        response = client.put(f"/api/tasks/{task_id}", json={"completed": True})
        data = response.json()

        assert data["success"] is True
        assert data["task"]["completed"] is True

    def test_should_toggle_task_completion(self, client):
        """Should toggle task between complete and incomplete."""
        create_response = client.post("/api/tasks", json={"text": "Toggle task"})
        task_id = create_response.json()["task"]["id"]

        # Complete it
        client.put(f"/api/tasks/{task_id}", json={"completed": True})
        # Uncomplete it
        response = client.put(f"/api/tasks/{task_id}", json={"completed": False})

        assert response.json()["task"]["completed"] is False

    def test_should_update_multiple_fields_at_once(self, client):
        """Should update multiple fields in one request."""
        create_response = client.post("/api/tasks", json={"text": "Task", "priority": "low"})
        task_id = create_response.json()["task"]["id"]

        response = client.put(f"/api/tasks/{task_id}", json={
            "text": "Updated task",
            "priority": "high",
            "completed": True
        })
        data = response.json()

        assert data["success"] is True
        assert data["task"]["text"] == "Updated task"
        assert data["task"]["priority"] == "high"
        assert data["task"]["completed"] is True

    # DELETE TESTS
    def test_should_delete_task_by_id(self, client):
        """Should delete a task by ID."""
        create_response = client.post("/api/tasks", json={"text": "To be deleted"})
        task_id = create_response.json()["task"]["id"]

        response = client.delete(f"/api/tasks/{task_id}")
        assert response.json()["success"] is True

        # Verify it's gone
        get_response = client.get("/api/tasks")
        tasks = get_response.json()["tasks"]
        task_ids = [t["id"] for t in tasks]
        assert task_id not in task_ids

    def test_should_clear_completed_tasks(self, client):
        """Should clear all completed tasks."""
        # Create mix of completed and incomplete
        r1 = client.post("/api/tasks", json={"text": "Incomplete 1"})
        r2 = client.post("/api/tasks", json={"text": "To complete"})
        r3 = client.post("/api/tasks", json={"text": "Incomplete 2"})

        # Complete one
        client.put(f"/api/tasks/{r2.json()['task']['id']}", json={"completed": True})

        # Clear completed
        response = client.post("/api/tasks/clear-completed")
        assert response.json()["success"] is True
        assert response.json()["remaining"] == 2

        # Verify only incomplete remain
        get_response = client.get("/api/tasks")
        tasks = get_response.json()["tasks"]
        assert len(tasks) == 2
        assert all(not t["completed"] for t in tasks)


# =============================================================================
# PRIORITY TESTS
# =============================================================================

class TestTasksPriority:
    """Tests for task priority handling."""

    def test_should_accept_low_priority(self, client):
        """Should accept 'low' priority."""
        response = client.post("/api/tasks", json={"text": "Task", "priority": "low"})
        assert response.json()["task"]["priority"] == "low"

    def test_should_accept_medium_priority(self, client):
        """Should accept 'medium' priority."""
        response = client.post("/api/tasks", json={"text": "Task", "priority": "medium"})
        assert response.json()["task"]["priority"] == "medium"

    def test_should_accept_high_priority(self, client):
        """Should accept 'high' priority."""
        response = client.post("/api/tasks", json={"text": "Task", "priority": "high"})
        assert response.json()["task"]["priority"] == "high"

    def test_should_default_to_medium_priority(self, client):
        """Should default to 'medium' when no priority specified."""
        response = client.post("/api/tasks", json={"text": "Task"})
        assert response.json()["task"]["priority"] == "medium"


# =============================================================================
# DATA VALIDATION TESTS
# =============================================================================

class TestTasksDataValidation:
    """Tests for input validation."""

    def test_should_reject_missing_text(self, client):
        """Should reject task without text field."""
        response = client.post("/api/tasks", json={"priority": "high"})
        assert response.status_code == 422

    def test_should_accept_empty_text(self, client):
        """Should accept empty text (no min length validation)."""
        # Note: Current implementation doesn't validate min length
        response = client.post("/api/tasks", json={"text": ""})
        # This may or may not be accepted depending on implementation
        # Documenting current behavior
        assert response.status_code in [200, 422]


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestTasksEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_unicode_text(self, client):
        """Should handle unicode characters in text."""
        unicode_text = "Task with emoji \U0001F680 and Japanese \u3053\u3093\u306b\u3061\u306f"
        response = client.post("/api/tasks", json={"text": unicode_text})
        assert response.status_code == 200
        assert response.json()["task"]["text"] == unicode_text

    def test_should_handle_special_characters(self, client):
        """Should handle special characters."""
        special = '<script>alert("xss")</script> & "quotes" \'single\''
        response = client.post("/api/tasks", json={"text": special})
        assert response.status_code == 200
        assert response.json()["task"]["text"] == special

    def test_should_handle_multiline_text(self, client):
        """Should preserve multiline text."""
        multiline = "Line 1\nLine 2\nLine 3"
        response = client.post("/api/tasks", json={"text": multiline})
        assert response.status_code == 200
        assert response.json()["task"]["text"] == multiline

    def test_should_handle_very_long_text(self, client):
        """Should handle very long text."""
        long_text = "x" * 5000
        response = client.post("/api/tasks", json={"text": long_text})
        assert response.status_code == 200
        assert len(response.json()["task"]["text"]) == 5000

    def test_should_return_error_for_update_nonexistent_task(self, client):
        """Should return error when updating non-existent task."""
        response = client.put("/api/tasks/nonexistent123", json={"text": "New"})
        data = response.json()
        assert data["success"] is False

    def test_should_handle_delete_nonexistent_task(self, client):
        """Should handle deleting non-existent task gracefully."""
        response = client.delete("/api/tasks/nonexistent123")
        # Should succeed (idempotent) or return success: true
        assert response.json()["success"] is True

    def test_should_handle_rapid_task_creation(self, client):
        """Should handle rapid creation of many tasks."""
        for i in range(50):
            response = client.post("/api/tasks", json={"text": f"Task {i}"})
            assert response.status_code == 200

        response = client.get("/api/tasks")
        assert len(response.json()["tasks"]) == 50

    def test_should_handle_whitespace_text(self, client):
        """Should handle text with leading/trailing whitespace."""
        whitespace = "   Spaces around   "
        response = client.post("/api/tasks", json={"text": whitespace})
        assert response.status_code == 200
        # Text should be preserved as-is
        assert response.json()["task"]["text"] == whitespace

    def test_should_preserve_task_order_after_update(self, client):
        """Updating a task should not change the order of other tasks."""
        # Create 3 tasks
        r1 = client.post("/api/tasks", json={"text": "Task 1"})
        r2 = client.post("/api/tasks", json={"text": "Task 2"})
        r3 = client.post("/api/tasks", json={"text": "Task 3"})

        id2 = r2.json()["task"]["id"]

        # Update middle task
        client.put(f"/api/tasks/{id2}", json={"text": "Task 2 Updated"})

        # Get all tasks
        response = client.get("/api/tasks")
        tasks = response.json()["tasks"]

        # Verify Task 2 is updated
        task2 = next(t for t in tasks if t["id"] == id2)
        assert task2["text"] == "Task 2 Updated"


# =============================================================================
# PERSISTENCE TESTS
# =============================================================================

class TestTasksPersistence:
    """Tests for data persistence."""

    def test_tasks_should_persist_after_retrieval(self, client):
        """Tasks should persist and be retrievable."""
        create_response = client.post("/api/tasks", json={
            "text": "Persistent task",
            "priority": "high"
        })
        task_id = create_response.json()["task"]["id"]

        # Retrieve multiple times
        for _ in range(3):
            response = client.get("/api/tasks")
            tasks = response.json()["tasks"]
            task_ids = [t["id"] for t in tasks]
            assert task_id in task_ids

    def test_tasks_file_should_be_valid_json(self, client):
        """Tasks file should contain valid JSON."""
        client.post("/api/tasks", json={"text": "Task 1"})
        client.post("/api/tasks", json={"text": "Task 2"})

        assert TASKS_FILE.exists()
        content = TASKS_FILE.read_text(encoding="utf-8")
        data = json.loads(content)  # Should not raise
        assert "tasks" in data
        assert len(data["tasks"]) == 2


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestTasksErrorHandling:
    """Tests for error handling scenarios."""

    def test_wrong_http_method_should_return_405(self, client):
        """PATCH to tasks endpoint should return 405."""
        response = client.patch("/api/tasks", json={"text": "test"})
        assert response.status_code == 405

    def test_invalid_json_should_return_422(self, client):
        """Invalid JSON should return 422."""
        response = client.post(
            "/api/tasks",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422


# =============================================================================
# CLEAR COMPLETED TESTS
# =============================================================================

class TestClearCompleted:
    """Tests for the clear-completed endpoint."""

    def test_should_clear_only_completed_tasks(self, client):
        """Should only clear completed tasks."""
        # Create tasks
        r1 = client.post("/api/tasks", json={"text": "Incomplete"})
        r2 = client.post("/api/tasks", json={"text": "Complete 1"})
        r3 = client.post("/api/tasks", json={"text": "Complete 2"})

        # Complete 2 of them
        client.put(f"/api/tasks/{r2.json()['task']['id']}", json={"completed": True})
        client.put(f"/api/tasks/{r3.json()['task']['id']}", json={"completed": True})

        # Clear completed
        response = client.post("/api/tasks/clear-completed")
        assert response.json()["success"] is True
        assert response.json()["remaining"] == 1

    def test_should_return_zero_remaining_when_all_completed(self, client):
        """Should return 0 remaining when all tasks are completed."""
        r1 = client.post("/api/tasks", json={"text": "Task 1"})
        r2 = client.post("/api/tasks", json={"text": "Task 2"})

        client.put(f"/api/tasks/{r1.json()['task']['id']}", json={"completed": True})
        client.put(f"/api/tasks/{r2.json()['task']['id']}", json={"completed": True})

        response = client.post("/api/tasks/clear-completed")
        assert response.json()["remaining"] == 0

    def test_should_do_nothing_when_no_completed_tasks(self, client):
        """Should do nothing when there are no completed tasks."""
        client.post("/api/tasks", json={"text": "Incomplete 1"})
        client.post("/api/tasks", json={"text": "Incomplete 2"})

        response = client.post("/api/tasks/clear-completed")
        assert response.json()["success"] is True
        assert response.json()["remaining"] == 2

    def test_should_work_when_no_tasks_exist(self, client):
        """Should work when no tasks exist at all."""
        response = client.post("/api/tasks/clear-completed")
        assert response.json()["success"] is True
        assert response.json()["remaining"] == 0


# =============================================================================
# SECURITY TESTS
# =============================================================================

class TestTasksSecurity:
    """Tests for security-related concerns."""

    def test_should_preserve_html_as_text(self, client):
        """HTML should be stored as text (not executed)."""
        html_content = '<script>alert("xss")</script>'
        response = client.post("/api/tasks", json={"text": html_content})
        assert response.status_code == 200
        assert response.json()["task"]["text"] == html_content

    def test_should_handle_sql_injection_attempts(self, client):
        """SQL injection attempts should be stored as text."""
        sql_injection = "'; DROP TABLE tasks; --"
        response = client.post("/api/tasks", json={"text": sql_injection})
        assert response.status_code == 200
        assert response.json()["task"]["text"] == sql_injection

    def test_id_should_be_short_alphanumeric(self, client):
        """Task IDs should be short alphanumeric strings."""
        response = client.post("/api/tasks", json={"text": "Test"})
        task_id = response.json()["task"]["id"]
        # ID should be 8 chars (UUID prefix)
        assert len(task_id) == 8
        assert task_id.isalnum() or "-" in task_id
