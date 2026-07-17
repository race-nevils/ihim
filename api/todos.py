"""To-Do API — quick-capture grouped to-do list.

Flat JSON file store (data/local/todos.json), same pattern as preferences:
dashboard scratch state, deliberately NOT part of the JSON-LD brain SSOT.
Categories group items (e.g. "desktop app", "Tomorrow"); items are
add / check / delete — a backlog capture surface, not a project tracker.
"""

import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from api.errors import problem
from api.runtime import DATA_DIR

router = APIRouter(prefix="/api/todos", tags=["todos"])

TODOS_PATH = DATA_DIR / "local" / "todos.json"


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class ItemCreate(BaseModel):
    category_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=500)


class ItemUpdate(BaseModel):
    done: bool


def _read() -> dict:
    if not TODOS_PATH.exists():
        return {"categories": []}
    try:
        data = json.loads(TODOS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"categories": []}
    if not isinstance(data, dict) or not isinstance(data.get("categories"), list):
        return {"categories": []}
    return data


def _write(data: dict) -> None:
    TODOS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TODOS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
    tmp.replace(TODOS_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("")
async def list_todos():
    """Full to-do tree: categories with their items."""
    return {"success": True, **_read()}


@router.post("/categories")
async def create_category(body: CategoryCreate, request: Request):
    data = _read()
    name = body.name.strip()
    if not name:
        return problem(400, "Category name cannot be blank", instance=request.url.path)
    if any(c["name"].lower() == name.lower() for c in data["categories"]):
        return problem(409, f"Category already exists: {name}", instance=request.url.path)
    category = {"id": uuid.uuid4().hex[:8], "name": name, "created_at": _now(), "items": []}
    data["categories"].append(category)
    _write(data)
    return {"success": True, "category": category}


@router.delete("/categories/{category_id}")
async def delete_category(category_id: str, request: Request):
    data = _read()
    remaining = [c for c in data["categories"] if c["id"] != category_id]
    if len(remaining) == len(data["categories"]):
        return problem(404, f"Category not found: {category_id}", instance=request.url.path)
    data["categories"] = remaining
    _write(data)
    return {"success": True}


@router.post("/items")
async def create_item(body: ItemCreate, request: Request):
    data = _read()
    text = body.text.strip()
    if not text:
        return problem(400, "To-do text cannot be blank", instance=request.url.path)
    category = next((c for c in data["categories"] if c["id"] == body.category_id), None)
    if category is None:
        return problem(404, f"Category not found: {body.category_id}", instance=request.url.path)
    item = {"id": uuid.uuid4().hex[:8], "text": text, "done": False, "created_at": _now()}
    category.setdefault("items", []).append(item)
    _write(data)
    return {"success": True, "item": item}


@router.patch("/items/{item_id}")
async def update_item(item_id: str, body: ItemUpdate, request: Request):
    data = _read()
    for category in data["categories"]:
        for item in category.get("items", []):
            if item["id"] == item_id:
                item["done"] = body.done
                _write(data)
                return {"success": True, "item": item}
    return problem(404, f"To-do not found: {item_id}", instance=request.url.path)


@router.delete("/items/{item_id}")
async def delete_item(item_id: str, request: Request):
    data = _read()
    for category in data["categories"]:
        items = category.get("items", [])
        remaining = [i for i in items if i["id"] != item_id]
        if len(remaining) != len(items):
            category["items"] = remaining
            _write(data)
            return {"success": True}
    return problem(404, f"To-do not found: {item_id}", instance=request.url.path)
