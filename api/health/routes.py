"""Health widget API — workout programs, nutrition plan, exercise glossary.

Serves parsed markdown from data/health/. The filename route takes a bare
name only: directory components are stripped (Path(...).name) and the file
must be .md and resolve inside the workouts directory — closing the path
traversal the old implementation allowed (`../../any/file`).
"""

import re
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter, Request

from api.errors import problem

router = APIRouter(prefix="/api/health", tags=["health"])

HEALTH_DATA_DIR = (Path(__file__).resolve().parents[2] / "data" / "health").resolve()


def _safe_workout_path(filename: str) -> Path | None:
    """Resolve a user-supplied workout filename safely or return None."""
    name = Path(filename).name  # strip any directory components
    if not name or not name.endswith(".md"):
        return None
    candidate = (HEALTH_DATA_DIR / "workouts" / name).resolve()
    if candidate.parent != (HEALTH_DATA_DIR / "workouts").resolve():
        return None
    return candidate


_DAY_RE = re.compile(r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)")


def parse_day_sections(content: str) -> List[Dict[str, Any]]:
    """Markdown -> [{day, title, primary_plan, minimum_dose, extras}]."""
    days = []
    for section in re.split(r"\n## ", content)[1:]:
        lines = section.strip().split("\n")
        if not lines:
            continue
        header = lines[0]
        day_match = _DAY_RE.match(header)
        if not day_match:
            continue
        content_text = "\n".join(lines[1:])
        primary = re.search(r"\*\*Primary Plan[^:]*:\*\*(.+?)(?=\*\*Minimum|\*\*[A-Z]|$)", content_text, re.DOTALL)
        minimum = re.search(r"\*\*Minimum Effective Dose[^:]*:\*\*(.+?)(?=\n\n---|\*\*[A-Z]|$)", content_text, re.DOTALL)
        extras_parts = re.split(r"\*\*Primary Plan[^:]*:\*\*|\*\*Minimum Effective Dose[^:]*:\*\*", content_text)
        days.append({
            "day": day_match.group(1),
            "title": header.split("—")[-1].strip(' "'),
            "primary_plan": primary.group(1).strip() if primary else "",
            "minimum_dose": minimum.group(1).strip() if minimum else "",
            "extras": extras_parts[0].strip() if extras_parts else "",
        })
    return days


def parse_nutrition_days(content: str) -> List[Dict[str, Any]]:
    """Markdown -> [{day, title, targets, meals{breakfast..snack}}]."""
    days = []
    for section in re.split(r"\n## ", content)[1:]:
        lines = section.strip().split("\n")
        if not lines:
            continue
        header = lines[0]
        day_match = _DAY_RE.match(header)
        if not day_match:
            continue
        content_text = "\n".join(lines[1:])
        targets = re.search(r"\*\*Targets:\*\*(.+?)(?=\n\*\*|$)", content_text, re.DOTALL)
        meals = {}
        for meal_type in ("Breakfast", "Lunch", "Dinner", "Snack"):
            m = re.search(rf"\*\*{meal_type}[^:]*:\*\*(.+?)(?=\n\*\*|\n---|\n##|$)", content_text, re.DOTALL)
            if m:
                meals[meal_type.lower()] = m.group(1).strip()
        days.append({
            "day": day_match.group(1),
            "title": header.split("—")[-1].strip(' "'),
            "targets": targets.group(1).strip() if targets else "",
            "meals": meals,
        })
    return days


def parse_glossary_sections(content: str) -> Dict[str, Any]:
    """Glossary markdown -> {global_cues, categories, substitution_map, checklist}."""
    global_cues = re.search(r"## Global Cues \(use everywhere\)(.+?)(?=\n---)", content, re.DOTALL)
    categories = []
    category_pattern = r"\n# ([A-H]\)) ([^\n]+)\n\n((?:## \d+\).*?\n(?:.*?\n)*?)+?)(?=\n# [A-H]\)|\n# Quick Substitution|$)"
    field_names = ("Target", "Setup", "Do", "Cues", "Errors", "Scale", "Goal", "Rule", "Avoid")
    for match in re.finditer(category_pattern, content, re.DOTALL):
        exercises = []
        for ex in re.finditer(r"## (\d+)\) ([^\n]+)\n(.*?)(?=\n## \d+\)|$)", match.group(3), re.DOTALL):
            entry: Dict[str, str] = {"number": ex.group(1), "name": ex.group(2).strip()}
            details = ex.group(3).strip()
            for field in field_names:
                entry[field.lower()] = ""
            for line in details.split("\n"):
                for field in field_names:
                    marker = f"**{field}:**"
                    if line.startswith(marker):
                        entry[field.lower()] = line.replace(marker, "").strip()
                        break
            exercises.append(entry)
        categories.append({
            "letter": match.group(1),
            "name": match.group(2).strip(),
            "exercises": exercises,
        })
    sub = re.search(r"# Quick Substitution Map(.+?)(?=\n# 10-Second)", content, re.DOTALL)
    checklist = re.search(r"# 10-Second Checklist(.+?)$", content, re.DOTALL)
    return {
        "global_cues": global_cues.group(1).strip() if global_cues else "",
        "categories": categories,
        "substitution_map": sub.group(1).strip() if sub else "",
        "checklist": checklist.group(1).strip() if checklist else "",
    }


@router.get("/workouts")
async def get_workouts(request: Request):
    """List available workout program files."""
    workouts_dir = HEALTH_DATA_DIR / "workouts"
    if not workouts_dir.exists():
        return problem(404, "Workouts directory not found", instance=request.url.path)
    return {"workouts": [f.name for f in workouts_dir.glob("*.md")]}


@router.get("/workouts/{filename}")
async def get_workout_content(filename: str, request: Request):
    """Parsed workout program by bare filename (must be .md in workouts/)."""
    file_path = _safe_workout_path(filename)
    if file_path is None:
        return problem(400, "Invalid workout filename", instance=request.url.path)
    if not file_path.exists():
        return problem(404, f"Workout file {file_path.name} not found", instance=request.url.path)
    content = file_path.read_text(encoding="utf-8")
    universal = re.search(r"## Universal Rules(.+?)(?=\n## [A-Z])", content, re.DOTALL)
    return {
        "filename": file_path.name,
        "universal_rules": universal.group(1).strip() if universal else "",
        "days": parse_day_sections(content),
    }


@router.get("/nutrition")
async def get_nutrition(request: Request):
    """Parsed nutrition meal plan."""
    file_path = HEALTH_DATA_DIR / "nutrition" / "hybrid_home_meal_plan.md"
    if not file_path.exists():
        return problem(404, "Nutrition file not found", instance=request.url.path)
    content = file_path.read_text(encoding="utf-8")
    rules = re.search(r"## Nutrition Rules(.+?)(?=\n## [A-Z])", content, re.DOTALL)
    staples = re.search(r"## Fast High-Protein Staples(.+?)(?=\n---|\n## [A-Z])", content, re.DOTALL)
    return {
        "nutrition_rules": rules.group(1).strip() if rules else "",
        "staples": staples.group(1).strip() if staples else "",
        "days": parse_nutrition_days(content),
    }


@router.get("/glossary")
async def get_glossary(request: Request):
    """Exercise glossary, parsed into categories."""
    file_path = HEALTH_DATA_DIR / "glossary" / "exercise_glossary.md"
    if not file_path.exists():
        return problem(404, "Glossary file not found", instance=request.url.path)
    return parse_glossary_sections(file_path.read_text(encoding="utf-8"))
