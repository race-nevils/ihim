"""
Tests for the Quick Notes/Scratchpad Feature

This module tests the Quick Notes functionality in the iHIM Command Center.
The feature allows users to quickly jot down notes, ideas, and reminders
with localStorage persistence on the frontend and optional API persistence.

Test Categories:
1. API Response Structure Tests
2. CRUD Operations Tests
3. Data Validation Tests
4. Edge Cases and Boundary Tests
5. Persistence and Ordering Tests
6. Error Handling Tests
7. Security Tests (XSS prevention, input sanitization)

Notes Architecture:
- Frontend: localStorage-based (ihim_notes key) with modal UI
- Backend API: /api/notes endpoints with JSON file persistence
"""
import pytest
from fastapi.testclient import TestClient
import sys
import json
from pathlib import Path
from datetime import datetime
import time

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.main import app, NOTES_FILE, save_notes, load_notes


@pytest.fixture
def client():
    """Create a test client for the FastAPI app."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_notes():
    """Clean up notes file before and after each test."""
    # Setup: Clear notes
    save_notes([])
    yield
    # Teardown: Clear notes
    save_notes([])


# =============================================================================
# RESPONSE STRUCTURE TESTS
# =============================================================================

class TestNotesResponseStructure:
    """Tests for validating the response structure of /api/notes endpoints."""

    def test_get_notes_should_return_200_status_code(self, client):
        """GET /api/notes should return 200 OK."""
        response = client.get("/api/notes")
        assert response.status_code == 200

    def test_get_notes_should_return_json_response(self, client):
        """GET /api/notes should return valid JSON."""
        response = client.get("/api/notes")
        assert response.headers["content-type"] == "application/json"
        data = response.json()
        assert isinstance(data, dict)

    def test_get_notes_should_contain_notes_array(self, client):
        """Response should contain a 'notes' array."""
        response = client.get("/api/notes")
        data = response.json()
        assert "notes" in data
        assert isinstance(data["notes"], list)

    def test_get_notes_should_return_empty_array_when_no_notes(self, client):
        """Response should contain empty array when no notes exist."""
        response = client.get("/api/notes")
        data = response.json()
        assert data["notes"] == []

    def test_create_note_should_return_201_status_code(self, client):
        """POST /api/notes should return 201 Created."""
        response = client.post("/api/notes", json={"content": "Test note"})
        assert response.status_code == 201

    def test_create_note_should_return_success_and_note(self, client):
        """POST /api/notes should return success flag and created note."""
        response = client.post("/api/notes", json={"content": "Test note"})
        data = response.json()
        assert data["success"] is True
        assert "note" in data
        assert isinstance(data["note"], dict)

    def test_note_should_have_required_fields(self, client):
        """Created note should have id, title, content, created_at, updated_at."""
        response = client.post("/api/notes", json={"content": "Test note"})
        note = response.json()["note"]

        assert "id" in note, "Note should have 'id' field"
        assert "title" in note, "Note should have 'title' field"
        assert "content" in note, "Note should have 'content' field"
        assert "created_at" in note, "Note should have 'created_at' field"
        assert "updated_at" in note, "Note should have 'updated_at' field"


# =============================================================================
# CRUD OPERATIONS TESTS
# =============================================================================

class TestNotesCRUDOperations:
    """Tests for Create, Read, Update, Delete operations."""

    # CREATE TESTS
    def test_should_create_note_with_content_only(self, client):
        """Should create note with content only (title optional)."""
        response = client.post("/api/notes", json={"content": "My first note"})
        data = response.json()
        assert data["success"] is True
        assert data["note"]["content"] == "My first note"
        assert data["note"]["title"] == ""  # Default empty title

    def test_should_create_note_with_title_and_content(self, client):
        """Should create note with both title and content."""
        response = client.post("/api/notes", json={
            "content": "Note body text",
            "title": "My Title"
        })
        data = response.json()
        assert data["success"] is True
        assert data["note"]["content"] == "Note body text"
        assert data["note"]["title"] == "My Title"

    def test_should_generate_unique_id_for_each_note(self, client):
        """Each note should have a unique ID."""
        response1 = client.post("/api/notes", json={"content": "Note 1"})
        response2 = client.post("/api/notes", json={"content": "Note 2"})
        response3 = client.post("/api/notes", json={"content": "Note 3"})

        id1 = response1.json()["note"]["id"]
        id2 = response2.json()["note"]["id"]
        id3 = response3.json()["note"]["id"]

        assert id1 != id2
        assert id2 != id3
        assert id1 != id3

    def test_should_generate_timestamps_on_creation(self, client):
        """created_at and updated_at should be set on creation."""
        before = datetime.utcnow().isoformat()
        response = client.post("/api/notes", json={"content": "Timestamped note"})
        after = datetime.utcnow().isoformat()

        note = response.json()["note"]
        # Timestamps should be ISO 8601 format with Z suffix
        assert note["created_at"].endswith("Z")
        assert note["updated_at"].endswith("Z")
        # created_at and updated_at should be the same on creation
        assert note["created_at"] == note["updated_at"]

    # READ TESTS
    def test_should_read_single_note_by_id(self, client):
        """Should retrieve a single note by ID."""
        # Create a note
        create_response = client.post("/api/notes", json={"content": "Test note"})
        note_id = create_response.json()["note"]["id"]

        # Read it back
        response = client.get(f"/api/notes/{note_id}")
        data = response.json()

        assert data["success"] is True
        assert data["note"]["id"] == note_id
        assert data["note"]["content"] == "Test note"

    def test_should_return_all_notes(self, client):
        """Should return all created notes."""
        # Create 3 notes
        client.post("/api/notes", json={"content": "Note 1"})
        client.post("/api/notes", json={"content": "Note 2"})
        client.post("/api/notes", json={"content": "Note 3"})

        # Get all notes
        response = client.get("/api/notes")
        notes = response.json()["notes"]

        assert len(notes) == 3

    # UPDATE TESTS
    def test_should_update_note_content(self, client):
        """Should update note content."""
        # Create a note
        create_response = client.post("/api/notes", json={"content": "Original"})
        note_id = create_response.json()["note"]["id"]

        # Update it
        response = client.put(f"/api/notes/{note_id}", json={"content": "Updated"})
        data = response.json()

        assert data["success"] is True
        assert data["note"]["content"] == "Updated"

    def test_should_update_note_title(self, client):
        """Should update note title."""
        # Create a note
        create_response = client.post("/api/notes", json={
            "content": "Body",
            "title": "Original Title"
        })
        note_id = create_response.json()["note"]["id"]

        # Update title only
        response = client.put(f"/api/notes/{note_id}", json={"title": "New Title"})
        data = response.json()

        assert data["success"] is True
        assert data["note"]["title"] == "New Title"
        assert data["note"]["content"] == "Body"  # Content unchanged

    def test_should_update_updated_at_timestamp_on_update(self, client):
        """updated_at should change when note is updated."""
        # Create a note
        create_response = client.post("/api/notes", json={"content": "Original"})
        note = create_response.json()["note"]
        original_updated_at = note["updated_at"]

        # Small delay to ensure timestamp difference
        time.sleep(0.1)

        # Update it
        response = client.put(f"/api/notes/{note['id']}", json={"content": "Updated"})
        updated_note = response.json()["note"]

        assert updated_note["updated_at"] != original_updated_at
        assert updated_note["created_at"] == note["created_at"]  # created_at unchanged

    # DELETE TESTS
    def test_should_delete_note_by_id(self, client):
        """Should delete a note by ID."""
        # Create a note
        create_response = client.post("/api/notes", json={"content": "To be deleted"})
        note_id = create_response.json()["note"]["id"]

        # Delete it
        response = client.delete(f"/api/notes/{note_id}")
        assert response.json()["success"] is True

        # Verify it's gone
        get_response = client.get(f"/api/notes/{note_id}")
        assert get_response.json()["success"] is False

    def test_should_delete_all_notes(self, client):
        """Should delete all notes."""
        # Create 3 notes
        client.post("/api/notes", json={"content": "Note 1"})
        client.post("/api/notes", json={"content": "Note 2"})
        client.post("/api/notes", json={"content": "Note 3"})

        # Delete all
        response = client.delete("/api/notes")
        assert response.json()["success"] is True

        # Verify all gone
        get_response = client.get("/api/notes")
        assert len(get_response.json()["notes"]) == 0


# =============================================================================
# DATA VALIDATION TESTS
# =============================================================================

class TestNotesDataValidation:
    """Tests for input validation."""

    def test_should_reject_empty_content(self, client):
        """Should reject note with empty content."""
        response = client.post("/api/notes", json={"content": ""})
        assert response.status_code == 422  # Validation error

    def test_should_reject_missing_content(self, client):
        """Should reject note without content field."""
        response = client.post("/api/notes", json={"title": "Title only"})
        assert response.status_code == 422

    def test_should_reject_content_exceeding_max_length(self, client):
        """Should reject content exceeding 10000 characters."""
        long_content = "x" * 10001
        response = client.post("/api/notes", json={"content": long_content})
        assert response.status_code == 422

    def test_should_accept_content_at_max_length(self, client):
        """Should accept content at exactly 10000 characters."""
        max_content = "x" * 10000
        response = client.post("/api/notes", json={"content": max_content})
        assert response.status_code == 201

    def test_should_reject_title_exceeding_max_length(self, client):
        """Should reject title exceeding 200 characters."""
        long_title = "T" * 201
        response = client.post("/api/notes", json={
            "content": "Body",
            "title": long_title
        })
        assert response.status_code == 422

    def test_should_accept_title_at_max_length(self, client):
        """Should accept title at exactly 200 characters."""
        max_title = "T" * 200
        response = client.post("/api/notes", json={
            "content": "Body",
            "title": max_title
        })
        assert response.status_code == 201

    def test_should_accept_minimum_length_content(self, client):
        """Should accept single character content."""
        response = client.post("/api/notes", json={"content": "X"})
        assert response.status_code == 201
        assert response.json()["note"]["content"] == "X"


# =============================================================================
# EDGE CASES AND BOUNDARY TESTS
# =============================================================================

class TestNotesEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_should_handle_unicode_content(self, client):
        """Should handle unicode characters in content."""
        unicode_content = "Hello! Emoji test: " + " ".join([
            "\U0001F600", "\U0001F4DD", "\U0001F680", "\U0001F44D"
        ])
        response = client.post("/api/notes", json={"content": unicode_content})
        assert response.status_code == 201
        assert response.json()["note"]["content"] == unicode_content

    def test_should_handle_unicode_title(self, client):
        """Should handle unicode characters in title."""
        unicode_title = "Japanese: " + "\u3053\u3093\u306b\u3061\u306f"
        response = client.post("/api/notes", json={
            "content": "Body",
            "title": unicode_title
        })
        assert response.status_code == 201
        assert response.json()["note"]["title"] == unicode_title

    def test_should_handle_multiline_content(self, client):
        """Should preserve multiline content."""
        multiline = "Line 1\nLine 2\nLine 3\n\nLine 5 (after blank)"
        response = client.post("/api/notes", json={"content": multiline})
        assert response.status_code == 201
        assert response.json()["note"]["content"] == multiline

    def test_should_handle_special_characters(self, client):
        """Should handle special characters."""
        special = '<script>alert("xss")</script> & "quotes" \'single\' `backticks`'
        response = client.post("/api/notes", json={"content": special})
        assert response.status_code == 201
        assert response.json()["note"]["content"] == special

    def test_should_handle_whitespace_content(self, client):
        """Should handle content with leading/trailing whitespace."""
        whitespace = "   Spaces around   "
        response = client.post("/api/notes", json={"content": whitespace})
        assert response.status_code == 201
        # Content should be preserved as-is (not trimmed)
        assert response.json()["note"]["content"] == whitespace

    def test_should_return_error_for_nonexistent_note_id(self, client):
        """Should return error for non-existent note ID."""
        response = client.get("/api/notes/nonexistent123")
        data = response.json()
        assert data["success"] is False
        assert "not found" in data["message"].lower()

    def test_should_return_error_for_update_nonexistent_note(self, client):
        """Should return error when updating non-existent note."""
        response = client.put("/api/notes/nonexistent123", json={"content": "New"})
        data = response.json()
        assert data["success"] is False

    def test_should_return_error_for_delete_nonexistent_note(self, client):
        """Should return error when deleting non-existent note."""
        response = client.delete("/api/notes/nonexistent123")
        data = response.json()
        assert data["success"] is False

    def test_should_handle_rapid_note_creation(self, client):
        """Should handle rapid creation of many notes."""
        for i in range(50):
            response = client.post("/api/notes", json={"content": f"Note {i}"})
            assert response.status_code == 201

        # Verify all created
        response = client.get("/api/notes")
        assert len(response.json()["notes"]) == 50

    def test_should_handle_empty_title_explicitly(self, client):
        """Should handle explicitly empty title."""
        response = client.post("/api/notes", json={
            "content": "Body",
            "title": ""
        })
        assert response.status_code == 201
        assert response.json()["note"]["title"] == ""


# =============================================================================
# ORDERING AND PERSISTENCE TESTS
# =============================================================================

class TestNotesOrdering:
    """Tests for note ordering and sorting."""

    def test_notes_should_be_sorted_by_updated_at_descending(self, client):
        """Notes should be returned with newest first."""
        # Create notes with slight delays
        client.post("/api/notes", json={"content": "First (oldest)"})
        time.sleep(0.05)
        client.post("/api/notes", json={"content": "Second"})
        time.sleep(0.05)
        client.post("/api/notes", json={"content": "Third (newest)"})

        # Get all notes
        response = client.get("/api/notes")
        notes = response.json()["notes"]

        assert notes[0]["content"] == "Third (newest)"
        assert notes[1]["content"] == "Second"
        assert notes[2]["content"] == "First (oldest)"

    def test_updated_note_should_move_to_top(self, client):
        """Updating a note should move it to the top of the list."""
        # Create notes
        r1 = client.post("/api/notes", json={"content": "First"})
        note1_id = r1.json()["note"]["id"]
        time.sleep(0.05)
        client.post("/api/notes", json={"content": "Second"})
        time.sleep(0.05)
        client.post("/api/notes", json={"content": "Third"})

        # Update the first (oldest) note
        time.sleep(0.05)
        client.put(f"/api/notes/{note1_id}", json={"content": "First (updated)"})

        # It should now be at the top
        response = client.get("/api/notes")
        notes = response.json()["notes"]

        assert notes[0]["content"] == "First (updated)"


class TestNotesPersistence:
    """Tests for data persistence."""

    def test_notes_should_persist_after_retrieval(self, client):
        """Notes should persist and be retrievable."""
        # Create a note
        create_response = client.post("/api/notes", json={
            "content": "Persistent note",
            "title": "Persistent"
        })
        note_id = create_response.json()["note"]["id"]

        # Retrieve it multiple times
        for _ in range(3):
            response = client.get(f"/api/notes/{note_id}")
            assert response.json()["success"] is True
            assert response.json()["note"]["content"] == "Persistent note"

    def test_notes_file_should_be_valid_json(self, client):
        """Notes file should contain valid JSON."""
        # Create some notes
        client.post("/api/notes", json={"content": "Note 1"})
        client.post("/api/notes", json={"content": "Note 2"})

        # Read the file directly
        assert NOTES_FILE.exists()
        content = NOTES_FILE.read_text(encoding="utf-8")
        data = json.loads(content)  # Should not raise
        assert "notes" in data
        assert len(data["notes"]) == 2


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================

class TestNotesErrorHandling:
    """Tests for error handling scenarios."""

    def test_wrong_http_method_should_return_405(self, client):
        """PATCH to notes endpoint should return 405."""
        response = client.patch("/api/notes", json={"content": "test"})
        assert response.status_code == 405

    def test_invalid_json_should_return_422(self, client):
        """Invalid JSON should return 422."""
        response = client.post(
            "/api/notes",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422

    def test_should_handle_concurrent_operations(self, client):
        """Should handle concurrent create and delete operations."""
        # Create a note
        r = client.post("/api/notes", json={"content": "Concurrent test"})
        note_id = r.json()["note"]["id"]

        # Simulate concurrent operations
        client.put(f"/api/notes/{note_id}", json={"content": "Updated"})
        client.delete(f"/api/notes/{note_id}")

        # Should be deleted
        response = client.get(f"/api/notes/{note_id}")
        assert response.json()["success"] is False


# =============================================================================
# SECURITY TESTS
# =============================================================================

class TestNotesSecurity:
    """Tests for security-related concerns."""

    def test_should_preserve_html_as_text(self, client):
        """HTML should be stored as text (not executed)."""
        html_content = '<script>alert("xss")</script><img src=x onerror=alert(1)>'
        response = client.post("/api/notes", json={"content": html_content})
        assert response.status_code == 201
        # Content should be preserved exactly
        assert response.json()["note"]["content"] == html_content

    def test_should_handle_sql_injection_attempts(self, client):
        """SQL injection attempts should be stored as text."""
        sql_injection = "'; DROP TABLE notes; --"
        response = client.post("/api/notes", json={"content": sql_injection})
        assert response.status_code == 201
        assert response.json()["note"]["content"] == sql_injection

    def test_should_not_execute_javascript_in_content(self, client):
        """JavaScript in content should not affect the API."""
        js_content = 'javascript:alert(document.cookie)'
        response = client.post("/api/notes", json={"content": js_content})
        assert response.status_code == 201
        # API should just store and return the text
        assert response.json()["note"]["content"] == js_content

    def test_id_should_not_contain_special_characters(self, client):
        """Note IDs should be alphanumeric (no path traversal)."""
        response = client.post("/api/notes", json={"content": "Test"})
        note_id = response.json()["note"]["id"]
        # ID should be alphanumeric/hyphen only
        assert note_id.replace("-", "").isalnum()


# =============================================================================
# FRONTEND LOCALSTORAGE COMPATIBILITY TESTS
# =============================================================================

class TestLocalStorageCompatibility:
    """
    Tests for frontend localStorage compatibility.

    The frontend uses a different data structure:
    - localStorage key: 'ihim_notes'
    - Note structure: { id, text, timestamp, updatedAt? }

    These tests document the expected frontend behavior.
    """

    def test_note_structure_for_frontend_consumption(self, client):
        """
        Document the API note structure.

        Frontend expects to map API notes to localStorage format.
        """
        response = client.post("/api/notes", json={
            "content": "Test note",
            "title": "Title"
        })
        note = response.json()["note"]

        # API structure (for documentation)
        assert "id" in note  # Maps to localStorage note.id
        assert "content" in note  # Maps to localStorage note.text
        assert "created_at" in note  # Maps to localStorage note.timestamp
        assert "updated_at" in note  # Maps to localStorage note.updatedAt

    def test_timestamp_format_is_iso8601(self, client):
        """Timestamps should be ISO 8601 format for JS Date parsing."""
        response = client.post("/api/notes", json={"content": "Test"})
        note = response.json()["note"]

        # Should be parseable by JavaScript Date()
        created_at = note["created_at"]
        assert created_at.endswith("Z")  # UTC indicator
        # Should match ISO format: YYYY-MM-DDTHH:MM:SS.ffffffZ
        datetime.fromisoformat(created_at.rstrip("Z"))  # Should not raise


# =============================================================================
# PERFORMANCE TESTS
# =============================================================================

class TestNotesPerformance:
    """Tests for performance characteristics."""

    def test_should_handle_100_notes_efficiently(self, client):
        """Should handle 100 notes without significant slowdown."""
        # Create 100 notes
        for i in range(100):
            client.post("/api/notes", json={"content": f"Performance test note {i}"})

        # Retrieval should still work
        response = client.get("/api/notes")
        notes = response.json()["notes"]
        assert len(notes) == 100

    def test_should_handle_large_note_content(self, client):
        """Should handle notes with large content (near max)."""
        large_content = "A" * 9999  # Just under max
        response = client.post("/api/notes", json={"content": large_content})
        assert response.status_code == 201

        # Retrieve it
        note_id = response.json()["note"]["id"]
        get_response = client.get(f"/api/notes/{note_id}")
        assert len(get_response.json()["note"]["content"]) == 9999

    def test_multiple_rapid_operations_should_succeed(self, client):
        """Should handle multiple rapid CRUD operations."""
        note_ids = []

        # Create rapidly
        for i in range(20):
            r = client.post("/api/notes", json={"content": f"Rapid {i}"})
            note_ids.append(r.json()["note"]["id"])

        # Update rapidly
        for note_id in note_ids[:10]:
            client.put(f"/api/notes/{note_id}", json={"content": "Updated"})

        # Delete rapidly
        for note_id in note_ids[10:]:
            client.delete(f"/api/notes/{note_id}")

        # Verify state
        response = client.get("/api/notes")
        assert len(response.json()["notes"]) == 10
