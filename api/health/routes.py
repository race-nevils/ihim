"""
Health sub-app API routes.
Provides endpoints for workouts and nutrition data.
"""
from pathlib import Path
from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any
import re

router = APIRouter(prefix="/api/health", tags=["health"])

HEALTH_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "health"


def parse_day_sections(content: str) -> List[Dict[str, Any]]:
    """
    Parse markdown file into day-by-day sections.
    Returns list of {day, title, primary_plan, minimum_dose, extras}
    """
    days = []

    # Split by day headers (##)
    sections = re.split(r'\n## ', content)

    for section in sections[1:]:  # Skip first section (header/rules)
        lines = section.strip().split('\n')
        if not lines:
            continue

        # First line is the day header
        header = lines[0]
        day_match = re.match(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', header)
        if not day_match:
            continue

        day = day_match.group(1)
        title = header.split('—')[-1].strip(' "')

        # Parse content sections
        content_text = '\n'.join(lines[1:])

        # Extract Primary Plan
        primary_match = re.search(r'\*\*Primary Plan[^:]*:\*\*(.+?)(?=\*\*Minimum|\*\*[A-Z]|$)',
                                 content_text, re.DOTALL)
        primary_plan = primary_match.group(1).strip() if primary_match else ""

        # Extract Minimum Effective Dose
        minimum_match = re.search(r'\*\*Minimum Effective Dose[^:]*:\*\*(.+?)(?=\n\n---|\*\*[A-Z]|$)',
                                 content_text, re.DOTALL)
        minimum_dose = minimum_match.group(1).strip() if minimum_match else ""

        # Extract extras (everything else in between)
        extras_parts = re.split(r'\*\*Primary Plan[^:]*:\*\*|\*\*Minimum Effective Dose[^:]*:\*\*',
                               content_text)
        extras = extras_parts[0].strip() if len(extras_parts) > 0 else ""

        days.append({
            "day": day,
            "title": title,
            "primary_plan": primary_plan,
            "minimum_dose": minimum_dose,
            "extras": extras
        })

    return days


def parse_nutrition_days(content: str) -> List[Dict[str, Any]]:
    """
    Parse nutrition markdown file into day-by-day meal plans.
    """
    days = []

    # Split by day headers (##)
    sections = re.split(r'\n## ', content)

    for section in sections[1:]:
        lines = section.strip().split('\n')
        if not lines:
            continue

        # First line is the day header
        header = lines[0]
        day_match = re.match(r'(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)', header)
        if not day_match:
            continue

        day = day_match.group(1)
        title = header.split('—')[-1].strip(' "')

        # Parse meals content
        content_text = '\n'.join(lines[1:])

        # Extract targets
        targets_match = re.search(r'\*\*Targets:\*\*(.+?)(?=\n\*\*|$)', content_text, re.DOTALL)
        targets = targets_match.group(1).strip() if targets_match else ""

        # Extract meals
        meals = {}
        for meal_type in ['Breakfast', 'Lunch', 'Dinner', 'Snack']:
            meal_match = re.search(rf'\*\*{meal_type}[^:]*:\*\*(.+?)(?=\n\*\*|\n---|\n##|$)',
                                  content_text, re.DOTALL)
            if meal_match:
                meals[meal_type.lower()] = meal_match.group(1).strip()

        days.append({
            "day": day,
            "title": title,
            "targets": targets,
            "meals": meals
        })

    return days


@router.get("/workouts")
async def get_workouts():
    """Get list of available workout programs."""
    workouts_dir = HEALTH_DATA_DIR / "workouts"

    if not workouts_dir.exists():
        raise HTTPException(status_code=404, detail="Workouts directory not found")

    files = [f.name for f in workouts_dir.glob("*.md")]
    return {"workouts": files}


@router.get("/workouts/{filename}")
async def get_workout_content(filename: str):
    """Get parsed workout content by filename."""
    file_path = HEALTH_DATA_DIR / "workouts" / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Workout file {filename} not found")

    content = file_path.read_text(encoding='utf-8')

    # Parse into day-by-day structure
    days = parse_day_sections(content)

    # Extract universal rules from header
    universal_match = re.search(r'## Universal Rules(.+?)(?=\n## [A-Z])', content, re.DOTALL)
    universal_rules = universal_match.group(1).strip() if universal_match else ""

    return {
        "filename": filename,
        "universal_rules": universal_rules,
        "days": days
    }


@router.get("/nutrition")
async def get_nutrition():
    """Get nutrition meal plan data."""
    file_path = HEALTH_DATA_DIR / "nutrition" / "hybrid_home_meal_plan.md"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Nutrition file not found")

    content = file_path.read_text(encoding='utf-8')

    # Parse into day-by-day structure
    days = parse_nutrition_days(content)

    # Extract nutrition rules from header
    rules_match = re.search(r'## Nutrition Rules(.+?)(?=\n## [A-Z])', content, re.DOTALL)
    nutrition_rules = rules_match.group(1).strip() if rules_match else ""

    # Extract staples
    staples_match = re.search(r'## Fast High-Protein Staples(.+?)(?=\n---|\n## [A-Z])', content, re.DOTALL)
    staples = staples_match.group(1).strip() if staples_match else ""

    return {
        "nutrition_rules": nutrition_rules,
        "staples": staples,
        "days": days
    }


def parse_glossary_sections(content: str) -> Dict[str, Any]:
    """
    Parse exercise glossary markdown into structured categories.
    Returns {global_cues, categories: [{name, exercises: [...]}], substitution_map, checklist}
    """
    # Extract global cues
    global_cues_match = re.search(r'## Global Cues \(use everywhere\)(.+?)(?=\n---)', content, re.DOTALL)
    global_cues = global_cues_match.group(1).strip() if global_cues_match else ""

    # Extract categories (A through H)
    categories = []
    category_pattern = r'\n# ([A-H]\)) ([^\n]+)\n\n((?:## \d+\).*?\n(?:.*?\n)*?)+?)(?=\n# [A-H]\)|\n# Quick Substitution|$)'

    for match in re.finditer(category_pattern, content, re.DOTALL):
        category_letter = match.group(1)
        category_name = match.group(2).strip()
        category_content = match.group(3)

        # Parse exercises within this category
        exercises = []
        exercise_pattern = r'## (\d+)\) ([^\n]+)\n(.*?)(?=\n## \d+\)|$)'

        for ex_match in re.finditer(exercise_pattern, category_content, re.DOTALL):
            number = ex_match.group(1)
            name = ex_match.group(2).strip()
            details = ex_match.group(3).strip()

            # Extract structured fields
            target = ""
            setup = ""
            do = ""
            cues = ""
            errors = ""
            scale = ""
            goal = ""
            rule = ""
            avoid = ""

            for line in details.split('\n'):
                if line.startswith('**Target:**'):
                    target = line.replace('**Target:**', '').strip()
                elif line.startswith('**Setup:**'):
                    setup = line.replace('**Setup:**', '').strip()
                elif line.startswith('**Do:**'):
                    do = line.replace('**Do:**', '').strip()
                elif line.startswith('**Cues:**'):
                    cues = line.replace('**Cues:**', '').strip()
                elif line.startswith('**Errors:**'):
                    errors = line.replace('**Errors:**', '').strip()
                elif line.startswith('**Scale:**'):
                    scale = line.replace('**Scale:**', '').strip()
                elif line.startswith('**Goal:**'):
                    goal = line.replace('**Goal:**', '').strip()
                elif line.startswith('**Rule:**'):
                    rule = line.replace('**Rule:**', '').strip()
                elif line.startswith('**Avoid:**'):
                    avoid = line.replace('**Avoid:**', '').strip()

            exercises.append({
                "number": number,
                "name": name,
                "target": target,
                "setup": setup,
                "do": do,
                "cues": cues,
                "errors": errors,
                "scale": scale,
                "goal": goal,
                "rule": rule,
                "avoid": avoid
            })

        categories.append({
            "letter": category_letter,
            "name": category_name,
            "exercises": exercises
        })

    # Extract substitution map
    sub_match = re.search(r'# Quick Substitution Map(.+?)(?=\n# 10-Second)', content, re.DOTALL)
    substitution_map = sub_match.group(1).strip() if sub_match else ""

    # Extract checklist
    checklist_match = re.search(r'# 10-Second Checklist(.+?)$', content, re.DOTALL)
    checklist = checklist_match.group(1).strip() if checklist_match else ""

    return {
        "global_cues": global_cues,
        "categories": categories,
        "substitution_map": substitution_map,
        "checklist": checklist
    }


@router.get("/glossary")
async def get_glossary():
    """Get exercise glossary with all movements from the program."""
    file_path = HEALTH_DATA_DIR / "glossary" / "exercise_glossary.md"

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Glossary file not found")

    content = file_path.read_text(encoding='utf-8')
    parsed = parse_glossary_sections(content)

    return parsed
