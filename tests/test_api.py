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


def test_security_headers_present(client):
    resp = client.get("/api/health")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert "Content-Security-Policy-Report-Only" in resp.headers


def test_api_responses_not_cached(client):
    resp = client.get("/api/health")
    assert "no-store" in resp.headers.get("Cache-Control", "")
