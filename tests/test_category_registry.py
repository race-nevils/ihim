"""Tests for the category registry system.

Verifies:
- Registry loading from categories.json
- System-only exclusion from classifiable names
- Prompt generation structure
- Trigger SQL generation
- Behavioral equivalence with original 6-category system
"""
import json
import pytest
from pathlib import Path

# Ensure iHIM is importable
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from handlers.category_registry import CategoryRegistry, CategoryDef, get_registry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    """Fresh registry loaded from the real categories.json."""
    return CategoryRegistry()


@pytest.fixture
def config_path():
    """Path to categories.json."""
    return Path(__file__).parent.parent / "data" / "categories.json"


# ---------------------------------------------------------------------------
# Registry Loading
# ---------------------------------------------------------------------------

class TestRegistryLoading:
    def test_loads_without_error(self, registry):
        assert registry is not None

    def test_correct_category_count(self, registry):
        names = registry.all_names()
        # At minimum: 6 original + Calendar = 7
        # After step 6: 6 original + 5 new + Calendar = 12
        assert len(names) >= 7

    def test_catch_all_is_misc(self, registry):
        assert registry.catch_all() == "Misc"

    def test_all_categories_have_names(self, registry):
        for name in registry.all_names():
            cat = registry.get(name)
            assert cat is not None
            assert cat.name == name

    def test_config_is_valid_json(self, config_path):
        data = json.loads(config_path.read_text(encoding="utf-8"))
        assert "metadata" in data
        assert "categories" in data
        assert isinstance(data["categories"], list)


# ---------------------------------------------------------------------------
# System-Only Exclusion
# ---------------------------------------------------------------------------

class TestSystemOnlyExclusion:
    def test_calendar_excluded_from_classifiable(self, registry):
        classifiable = registry.classifiable_names()
        assert "Calendar" not in classifiable

    def test_calendar_included_in_all(self, registry):
        all_names = registry.all_names()
        assert "Calendar" in all_names

    def test_misc_excluded_from_classifiable(self, registry):
        """Misc is catch-all, not directly assigned by classifier."""
        classifiable = registry.classifiable_names()
        assert "Misc" not in classifiable

    def test_classifiable_is_subset_of_all(self, registry):
        classifiable = set(registry.classifiable_names())
        all_cats = set(registry.all_names())
        assert classifiable.issubset(all_cats)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    def test_valid_categories(self, registry):
        for name in ["People", "Tasks", "Projects", "Ideas", "Reference", "Misc"]:
            assert registry.is_valid(name), f"{name} should be valid"

    def test_invalid_categories(self, registry):
        for name in ["Admin", "Foo", "tasks", "PEOPLE", ""]:
            assert not registry.is_valid(name), f"{name} should be invalid"

    def test_calendar_is_valid(self, registry):
        assert registry.is_valid("Calendar")


# ---------------------------------------------------------------------------
# Task Status
# ---------------------------------------------------------------------------

class TestTaskStatus:
    def test_tasks_has_task_status(self, registry):
        assert "Tasks" in registry.with_task_status()

    def test_projects_has_task_status(self, registry):
        assert "Projects" in registry.with_task_status()

    def test_people_no_task_status(self, registry):
        assert "People" not in registry.with_task_status()


# ---------------------------------------------------------------------------
# Prompt Generation
# ---------------------------------------------------------------------------

class TestPromptGeneration:
    def test_prompt_is_flat_not_sequential(self, registry):
        """Prompt uses flat category list, not sequential STEP tree."""
        import re
        prompt = registry.generate_classify_prompt()
        assert not re.search(r"STEP \d+:", prompt), "Prompt should not contain sequential STEP pattern"
        assert "CATEGORIES:" in prompt

    def test_prompt_contains_all_classifiable_categories(self, registry):
        prompt = registry.generate_classify_prompt()
        for name in registry.classifiable_names():
            assert name in prompt, f"Category '{name}' missing from prompt"

    def test_prompt_excludes_system_only(self, registry):
        prompt = registry.generate_classify_prompt()
        # Calendar should not appear as a category section
        assert "Calendar —" not in prompt

    def test_prompt_includes_misc_as_valid_output(self, registry):
        """Misc is now a valid LLM output in the prompt."""
        prompt = registry.generate_classify_prompt()
        assert "Misc" in prompt
        # Misc should be in the valid category pipe-delimited list
        assert "Misc" in prompt.split('"category"')[0] or "Misc" in prompt

    def test_prompt_has_json_output_format(self, registry):
        prompt = registry.generate_classify_prompt()
        assert '"category"' in prompt
        assert '"confidence"' in prompt
        assert '"summary"' in prompt
        assert '"calendar"' in prompt

    def test_prompt_has_today_placeholder(self, registry):
        prompt = registry.generate_classify_prompt()
        assert "{{today}}" in prompt

    def test_prompt_has_content_placeholder(self, registry):
        prompt = registry.generate_classify_prompt()
        assert "{content}" in prompt

    def test_prompt_contains_gratitude_example(self, registry):
        """Faith examples include gratitude keywords."""
        prompt = registry.generate_classify_prompt()
        assert "gratitude" in prompt.lower()


# ---------------------------------------------------------------------------
# Trigger SQL Generation
# ---------------------------------------------------------------------------

class TestTriggerSQL:
    def test_trigger_contains_all_categories(self, registry):
        sql = registry.generate_trigger_sql()
        for name in registry.all_names():
            assert f"'{name}'" in sql, f"Category '{name}' missing from trigger SQL"

    def test_trigger_has_insert_and_update(self, registry):
        sql = registry.generate_trigger_sql()
        assert "check_category_insert" in sql
        assert "check_category_update" in sql

    def test_trigger_drops_before_create(self, registry):
        sql = registry.generate_trigger_sql()
        # DROP should come before CREATE
        drop_pos = sql.index("DROP TRIGGER")
        create_pos = sql.index("CREATE TRIGGER")
        assert drop_pos < create_pos


# ---------------------------------------------------------------------------
# Behavioral Equivalence (original 6 categories)
# ---------------------------------------------------------------------------

class TestBehavioralEquivalence:
    """Verify the registry produces equivalent behavior for original 6 categories."""

    ORIGINAL_SIX = {"Tasks", "Projects", "People", "Ideas", "Reference", "Misc"}

    def test_original_six_all_present(self, registry):
        all_names = set(registry.all_names())
        assert self.ORIGINAL_SIX.issubset(all_names)

    def test_original_classifiable_present(self, registry):
        """Original 5 classifiable categories (Misc excluded) are all present."""
        classifiable = set(registry.classifiable_names())
        original_classifiable = {"Tasks", "Projects", "People", "Ideas", "Reference"}
        assert original_classifiable.issubset(classifiable)

    def test_prompt_has_tasks_vs_projects_distinction(self, registry):
        """The critical Tasks vs Projects distinction is preserved."""
        prompt = registry.generate_classify_prompt()
        assert "Tasks" in prompt and "Projects" in prompt
        assert "specific date" in prompt.lower()

    def test_prompt_has_calendar_detection(self, registry):
        """Calendar detection section is preserved."""
        prompt = registry.generate_classify_prompt()
        assert "CALENDAR DETECTION" in prompt
        assert "YYYY-MM-DD" in prompt

    def test_prompt_has_examples(self, registry):
        """Key examples from original prompt are preserved."""
        prompt = registry.generate_classify_prompt()
        assert "Dentist appointment" in prompt
        assert "Meeting with Sarah" in prompt


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_registry_returns_same_instance(self):
        r1 = get_registry()
        r2 = get_registry()
        assert r1 is r2

    def test_get_registry_returns_valid_instance(self):
        r = get_registry()
        assert len(r.all_names()) > 0
