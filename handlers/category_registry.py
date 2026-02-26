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
        """Build the LLM classification decision tree from config.

        Produces a prompt functionally equivalent to the hardcoded CLASSIFY_PROMPT
        in handlers/utils.py for backward compatibility.
        """
        # Gather classifiable categories with a step, sorted by step
        stepped = [
            c for c in self._categories.values()
            if c.classifier_step is not None and not c.is_system_only
        ]
        stepped.sort(key=lambda c: c.classifier_step)

        # Build decision tree steps
        steps = []
        total_steps = len(stepped)
        for i, cat in enumerate(stepped):
            step_num = i + 1
            question = cat.classifier_question or f"Does this belong in {cat.name}?"
            if step_num < total_steps:
                next_step = step_num + 1
                step_text = (
                    f"STEP {step_num}: {question}\n"
                    f"  → YES: Category = \"{cat.name}\"\n"
                    f"  → NO: Continue to Step {next_step}"
                )
            else:
                # Last step — default fallback to Ideas for unclear content
                step_text = (
                    f"STEP {step_num}: {question}\n"
                    f"  → YES: Category = \"{cat.name}\"\n"
                    f"  → NO: Category = \"Ideas\" (default for unclear content)"
                )
            steps.append(step_text)

        decision_tree = "\n\n".join(steps)

        # Build valid category list for JSON output (excludes catch-all and system-only)
        valid_cats = "|".join(self.classifiable_names())

        # Build examples from config
        example_lines = []
        for cat in stepped:
            for ex in cat.examples:
                # Map examples to their expected output
                example_lines.append(f"- \"{ex}\" → {cat.name}")

        examples_text = "\n".join(example_lines) if example_lines else ""

        # Key distinctions (Tasks vs Projects is critical for the classifier)
        distinctions = (
            "KEY DISTINCTION - Tasks vs Projects:\n"
            "- Tasks = has a specific date/time, goes on calendar, displayed chronologically\n"
            "- Projects = no specific date, \"anytime\" items that just need to get done eventually"
        )

        prompt = (
            f"Classify this note into exactly ONE category by following this decision tree IN ORDER:\n\n"
            f"{decision_tree}\n\n"
            f"{distinctions}\n\n"
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
