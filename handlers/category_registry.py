"""Category registry — single source of truth for all brain categories.

Loads from data/categories.json and exposes a clean interface for every
part of the system that needs to know about categories.

Pattern: JSON-backed lazy singleton (same as handlers/entity.py).
Import direction: this module imports nothing from handlers/ — no circular deps.
"""
import json
from pathlib import Path
from typing import Optional

IHIM_ROOT = Path(__file__).parent.parent
CATEGORIES_PATH = IHIM_ROOT / "data" / "categories.json"


class CategoryDef:
    """Single category definition from the registry."""

    __slots__ = (
        "name", "description", "classifier_step", "classifier_question",
        "examples", "anti_examples", "is_catch_all", "has_task_status",
        "is_system_only", "sort_order",
    )

    def __init__(self, data: dict):
        self.name: str = data["name"]
        self.description: str = data.get("description", "")
        self.classifier_step: Optional[int] = data.get("classifier_step")
        self.classifier_question: Optional[str] = data.get("classifier_question")
        self.examples: list[str] = data.get("examples", [])
        self.anti_examples: list[str] = data.get("anti_examples", [])
        self.is_catch_all: bool = data.get("is_catch_all", False)
        self.has_task_status: bool = data.get("has_task_status", False)
        self.is_system_only: bool = data.get("is_system_only", False)
        self.sort_order: int = data.get("sort_order", 50)


class CategoryRegistry:
    """Registry of all brain categories, loaded from categories.json."""

    def __init__(self, config_path: Path = CATEGORIES_PATH):
        data = json.loads(config_path.read_text(encoding="utf-8"))
        self._categories: dict[str, CategoryDef] = {}
        for entry in data["categories"]:
            cat = CategoryDef(entry)
            self._categories[cat.name] = cat

    # --- Query methods ---

    def all_names(self) -> list[str]:
        """All category names including system-only, sorted by sort_order."""
        return [c.name for c in sorted(self._categories.values(), key=lambda c: c.sort_order)]

    def classifiable_names(self) -> list[str]:
        """Categories the LLM can assign (excludes system-only and catch-all)."""
        return [
            c.name for c in sorted(self._categories.values(), key=lambda c: c.sort_order)
            if not c.is_system_only and not c.is_catch_all
        ]

    def is_valid(self, name: str) -> bool:
        """Check if a category name exists in the registry."""
        return name in self._categories

    def get(self, name: str) -> Optional[CategoryDef]:
        """Get full category definition by name."""
        return self._categories.get(name)

    def catch_all(self) -> str:
        """Return the catch-all category name (Misc)."""
        for cat in self._categories.values():
            if cat.is_catch_all:
                return cat.name
        return "Misc"

    def with_task_status(self) -> list[str]:
        """Categories that get task completion tracking."""
        return [c.name for c in self._categories.values() if c.has_task_status]

    # --- Code generation methods ---

    def generate_classify_prompt(self) -> str:
        """Build the LLM classification prompt from config.

        Produces a flat category list (not a sequential decision tree).
        The LLM sees all categories simultaneously and picks the best fit.
        """
        # Build flat category sections sorted by sort_order
        sorted_cats = sorted(
            (c for c in self._categories.values()
             if not c.is_system_only and not c.is_catch_all),
            key=lambda c: c.sort_order,
        )

        sections = []
        for cat in sorted_cats:
            question = cat.classifier_question or f"Does this belong in {cat.name}?"
            lines = [f"{cat.name} — {cat.description}"]
            if cat.examples:
                lines.append("  Examples: " + "; ".join(f'"{ex}"' for ex in cat.examples))
            lines.append(f"  Ask: {question}")
            sections.append("\n".join(lines))

        # Append Misc explicitly as the catch-all
        catch_all = self.catch_all()
        sections.append(
            f"{catch_all} — None of the above fit well\n"
            f"  Use when: The note doesn't clearly belong in any specific category, or you're unsure."
        )

        category_list = "\n\n".join(sections)

        # Valid categories for JSON output: classifiable + catch-all
        valid_cats = "|".join(self.classifiable_names() + [catch_all])

        prompt = (
            f"Classify this note into exactly ONE category. Pick the BEST fit from the list below.\n\n"
            f"CATEGORIES:\n\n"
            f"{category_list}\n\n"
            f"RULES:\n"
            f"- Pick the SINGLE best-fit category based on the PRIMARY purpose of the note\n"
            f"- KEY DISTINCTION: Tasks = has specific date/time; Projects = undated actions\n"
            f"- Daily gratitude, blessings, thankfulness → Faith (even if food or health is mentioned)\n"
            f"- Health = physical wellness as the PRIMARY topic (workouts, medical, meal plans)\n"
            f"- If genuinely unsure, choose Misc — don't force a bad fit\n"
            f"- TITLE DATES: If the title contains a date (e.g., \"3/9/26 Gratitude\"), that is when the note was WRITTEN — it is NOT a calendar event. Only create calendar events from dates in the note BODY.\n\n"
            f"CALENDAR DETECTION (check independently of category):\n"
            f"Does this note mention a SPECIFIC DATE or TIME for an event, appointment, meeting, or deadline?\n"
            f"  → YES: Set \"calendar\" with extracted date info\n"
            f"  → NO: Set \"calendar\" to null\n\n"
            f"Calendar rules:\n"
            f"- Date + time mentioned → all_day = false, include time\n"
            f"- Date only, no time → all_day = true, time = null\n"
            f"- No specific date → calendar = null\n"
            f"- Use ISO format for date: YYYY-MM-DD\n"
            f"- Use 24h format for time: HH:MM\n"
            f"- If a time RANGE is given (e.g., \"8am-10am\", \"8:30am to 10:30am\"), set both \"time\" (start) and \"end_time\" (end)\n"
            f"- If only start time, set \"end_time\" to null\n"
            f"- Day name alone (\"Friday\") → resolve to the UPCOMING occurrence from today's date\n"
            f"- \"next Friday\" → the Friday of NEXT week (always 7+ days away)\n"
            f"- \"this Friday\" → the Friday of THIS week\n\n"
            f"EXAMPLES:\n"
            f"- \"Dentist appointment February 2nd\" → Tasks, calendar: {{{{\"is_event\": true, \"title\": \"Dentist Appointment\", \"date\": \"2026-02-02\", \"time\": null, \"all_day\": true}}}}\n"
            f"- \"Meeting with Sarah at 3pm on Feb 4th\" → People, calendar: {{{{\"is_event\": true, \"title\": \"Meeting with Sarah\", \"date\": \"2026-02-04\", \"time\": \"15:00\", \"all_day\": false}}}}\n"
            f"- \"Tax documents due by Feb 16th\" → Tasks, calendar: {{{{\"is_event\": true, \"title\": \"Tax Documents Due\", \"date\": \"2026-02-16\", \"time\": null, \"all_day\": true}}}}\n"
            f"- \"Need to clean oil from prop\" → Projects, calendar: null (action but no date = Project)\n"
            f"- \"Build a waitlist signup feature\" → Projects, calendar: null (multi-step, no deadline)\n"
            f"- \"The widget isn't working, I want it on the main dashboard\" → Projects, calendar: null (complaint + intent = action item, no date)\n"
            f"- \"What if we used Redis?\" → Ideas, calendar: null (no date, no action)\n"
            f"- \"Sarah's phone number is 555-1234\" → People, calendar: null (no date)\n\n"
            f"Return ONLY valid JSON:\n"
            f"{{{{\"category\": \"<{valid_cats}>\", \"confidence\": <0.0-1.0>, \"summary\": \"<1 sentence describing the note>\", "
            f"\"calendar\": null | {{{{\"is_event\": true, \"title\": \"<short event title>\", \"date\": \"<YYYY-MM-DD>\", \"time\": \"<HH:MM>\" | null, \"end_time\": \"<HH:MM>\" | null, \"all_day\": <true|false>}}}}}}}}}}\n\n"
            f"Today's date: {{{{today}}}}\n\n"
            f"Note: {{content}}\n\n"
            f"JSON response:"
        )
        return prompt

    def generate_trigger_sql(self) -> str:
        """Build SQLite trigger SQL for category validation.

        Returns SQL that drops existing triggers and creates new ones
        with the current category list.
        """
        all_names = self.all_names()
        values = ",".join(f"'{name}'" for name in all_names)

        return (
            f"DROP TRIGGER IF EXISTS check_category_insert;\n"
            f"DROP TRIGGER IF EXISTS check_category_update;\n\n"
            f"CREATE TRIGGER check_category_insert\n"
            f"BEFORE INSERT ON entries\n"
            f"BEGIN\n"
            f"    SELECT CASE\n"
            f"        WHEN NEW.category NOT IN ({values})\n"
            f"        THEN RAISE(ABORT, 'Invalid category')\n"
            f"    END;\n"
            f"END;\n\n"
            f"CREATE TRIGGER check_category_update\n"
            f"BEFORE UPDATE OF category ON entries\n"
            f"BEGIN\n"
            f"    SELECT CASE\n"
            f"        WHEN NEW.category NOT IN ({values})\n"
            f"        THEN RAISE(ABORT, 'Invalid category')\n"
            f"    END;\n"
            f"END;"
        )


# ---------------------------------------------------------------------------
# Module-level lazy singleton
# ---------------------------------------------------------------------------

_registry: Optional[CategoryRegistry] = None


def get_registry() -> CategoryRegistry:
    """Get or create the singleton CategoryRegistry instance."""
    global _registry
    if _registry is None:
        _registry = CategoryRegistry()
    return _registry
