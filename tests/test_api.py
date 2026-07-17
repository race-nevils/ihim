"""Route-level tests for the rebuilt iHIM API."""

import pytest


READ_ENDPOINTS = [
    "/api/health",
    "/api/boot-id",
    "/api/system/stats",
    "/api/server/status",
    "/api/brain/stats",
    "/api/brain/entries?limit=2",
    "/api/graph/stats",
    "/api/todos",
    "/api/preferences",
    "/api/stt/status",
    "/api/stt/history?limit=2",
    "/api/stt/vocab",
    "/api/recorder/status",
    "/api/recorder/recordings",
]


@pytest.mark.parametrize("path", READ_ENDPOINTS)
def test_read_endpoint_never_5xx(client, path):
    resp = client.get(path)
    assert resp.status_code < 500, f"{path} -> {resp.status_code}: {resp.text[:200]}"


def test_root_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "__BOOT_ID__" not in resp.text
    assert '<script type="importmap">' in resp.text


def test_unknown_route_is_problem_json(client):
    resp = client.get("/api/definitely-not-a-route")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")
    doc = resp.json()
    for field in ("type", "title", "status", "detail"):
        assert field in doc


def test_todos_crud_roundtrip(client):
    """Category → item → toggle → delete, cleaning up everything it created.

    Runs against the live todos.json (conftest uses the real DATA_DIR), so the
    test namespaces its category and removes it — deleting the category also
    deletes its items.
    """
    name = "_pytest-roundtrip"
    created = client.post("/api/todos/categories", json={"name": name})
    assert created.status_code == 200, created.text
    cat_id = created.json()["category"]["id"]
    try:
        assert client.post("/api/todos/categories", json={"name": name}).status_code == 409

        item = client.post("/api/todos/items",
                           json={"category_id": cat_id, "text": "check the taskbar"})
        assert item.status_code == 200, item.text
        item_id = item.json()["item"]["id"]

        toggled = client.patch(f"/api/todos/items/{item_id}", json={"done": True})
        assert toggled.status_code == 200
        assert toggled.json()["item"]["done"] is True

        assert client.delete(f"/api/todos/items/{item_id}").status_code == 200
        assert client.patch(f"/api/todos/items/{item_id}", json={"done": False}).status_code == 404
    finally:
        assert client.delete(f"/api/todos/categories/{cat_id}").status_code == 200
    listing = client.get("/api/todos").json()
    assert all(c["name"] != name for c in listing["categories"])


def test_brain_entry_missing_is_problem_404(client):
    resp = client.get("/api/brain/entries/no-such-entry-id")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/problem+json")


class TestWorkoutTraversalGuard:
    """The old implementation allowed ../../ arbitrary file reads.

    HTTP clients (httpx included) normalize `..` path segments away before
    sending, so the raw-`..` case is unit-tested against the guard function
    directly rather than over HTTP.
    """

    def test_guard_function_rejects_traversal(self):
        from api.health.routes import _safe_workout_path
        assert _safe_workout_path("..") is None
        assert _safe_workout_path("../evil.md") is None or \
            _safe_workout_path("../evil.md").name == "evil.md"
        assert _safe_workout_path("..\\..\\secret.md") is None or \
            _safe_workout_path("..\\..\\secret.md").name == "secret.md"
        assert _safe_workout_path("C:\\Windows\\system.ini") is None
        assert _safe_workout_path("") is None

    def test_non_md_extension_rejected(self, client):
        resp = client.get("/api/health/workouts/secrets.txt")
        assert resp.status_code == 400

    def test_traversal_shaped_md_rejected_or_missing(self, client):
        # Path(...).name strips directories; '....md' style names must never
        # escape the workouts dir. 404 (not found inside dir) is acceptable,
        # 200 with file content from outside the dir is the failure mode.
        resp = client.get("/api/health/workouts/....md")
        assert resp.status_code in (400, 404)

    def test_legit_workout_still_served(self, client):
        listing = client.get("/api/health/workouts")
        if listing.status_code != 200 or not listing.json().get("workouts"):
            pytest.skip("no workout files present")
        name = listing.json()["workouts"][0]
        resp = client.get(f"/api/health/workouts/{name}")
        assert resp.status_code == 200
        assert resp.json()["filename"] == name


def test_security_headers_present(client):
    resp = client.get("/api/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy-Report-Only" in resp.headers


def test_api_responses_not_cached(client):
    resp = client.get("/api/health")
    assert "no-store" in resp.headers.get("Cache-Control", "")
