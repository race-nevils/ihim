"""Tests for deterministic fallback: date extraction and summary validation."""
import pytest
from datetime import date
from unittest.mock import patch

from handlers.fallback import extract_date, validate_summary


# ── Date extraction: month name patterns ──────────────────────────


class TestDateExtractionMonthNames:
    def test_month_day_ordinal(self):
        result = extract_date("I need to bring the trees inside Feb 2nd in the morning")
        assert result is not None
        assert result["is_event"] is True
        assert result["date"] == "2026-02-02"
        assert result["all_day"] is False
        assert result["time"] == "09:00"  # "in the morning"

    def test_month_day_no_ordinal(self):
        result = extract_date("Dentist appointment February 2")
        assert result is not None
        assert result["date"].endswith("-02-02")

    def test_month_day_with_year(self):
        result = extract_date("Conference on March 15th, 2027")
        assert result is not None
        assert result["date"] == "2027-03-15"
        assert result["all_day"] is True

    def test_month_day_st_suffix(self):
        result = extract_date("Meeting on January 1st")
        assert result is not None
        assert result["date"].endswith("-01-01")

    def test_month_day_nd_suffix(self):
        result = extract_date("Due on March 2nd")
        assert result is not None
        assert result["date"].endswith("-03-02")

    def test_month_day_rd_suffix(self):
        result = extract_date("Party on April 3rd")
        assert result is not None
        assert result["date"].endswith("-04-03")

    def test_month_day_th_suffix(self):
        result = extract_date("Flight on June 15th")
        assert result is not None
        assert result["date"].endswith("-06-15")

    def test_full_month_name(self):
        result = extract_date("September 20 is the deadline")
        assert result is not None
        assert result["date"].endswith("-09-20")

    def test_abbreviated_month(self):
        result = extract_date("Dec 25 family dinner")
        assert result is not None
        assert result["date"].endswith("-12-25")


# ── Date extraction: numeric patterns ─────────────────────────────


class TestDateExtractionNumeric:
    def test_numeric_with_year(self):
        result = extract_date("Submit by 1/15/2026")
        assert result is not None
        assert result["date"] == "2026-01-15"

    def test_numeric_without_year(self):
        result = extract_date("Appointment on 3/10")
        assert result is not None
        assert result["date"].endswith("-03-10")


# ── Date extraction: time patterns ────────────────────────────────


class TestTimeExtraction:
    def test_time_pm(self):
        result = extract_date("Meeting with Sarah at 3pm on Feb 4th")
        assert result is not None
        assert result["time"] == "15:00"
        assert result["all_day"] is False

    def test_time_am(self):
        result = extract_date("Gym at 7am on March 1st")
        assert result is not None
        assert result["time"] == "07:00"
        assert result["all_day"] is False

    def test_time_with_minutes(self):
        result = extract_date("Call at 3:30pm on Feb 10th")
        assert result is not None
        assert result["time"] == "15:30"

    def test_time_12pm(self):
        result = extract_date("Lunch at 12pm on Feb 5th")
        assert result is not None
        assert result["time"] == "12:00"

    def test_time_12am(self):
        result = extract_date("Deadline at 12am on Feb 5th")
        assert result is not None
        assert result["time"] == "00:00"

    def test_morning(self):
        result = extract_date("Bring trees inside Feb 2nd in the morning")
        assert result is not None
        assert result["time"] == "09:00"
        assert result["all_day"] is False

    def test_afternoon(self):
        result = extract_date("Haircut Feb 10th in the afternoon")
        assert result is not None
        assert result["time"] == "14:00"

    def test_evening(self):
        result = extract_date("Dinner party March 5th in the evening")
        assert result is not None
        assert result["time"] == "18:00"

    def test_noon(self):
        result = extract_date("Meet at noon on Feb 14th")
        assert result is not None
        assert result["time"] == "12:00"

    def test_midnight(self):
        result = extract_date("Deadline at midnight on Feb 28th")
        assert result is not None
        assert result["time"] == "00:00"

    def test_no_time_means_all_day(self):
        result = extract_date("Tax deadline February 16th")
        assert result is not None
        assert result["all_day"] is True
        assert result["time"] is None


# ── Date extraction: year inference ───────────────────────────────


class TestYearInference:
    @patch("handlers.fallback.date")
    def test_past_date_uses_next_year(self, mock_date):
        mock_date.today.return_value = date(2026, 6, 15)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = extract_date("Event on Jan 5th")
        assert result is not None
        assert result["date"] == "2027-01-05"

    @patch("handlers.fallback.date")
    def test_future_date_uses_current_year(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 15)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = extract_date("Event on March 10th")
        assert result is not None
        assert result["date"] == "2026-03-10"

    def test_explicit_year_respected(self):
        result = extract_date("Conference on March 15th, 2028")
        assert result is not None
        assert result["date"] == "2028-03-15"


# ── Date extraction: no-date and invalid cases ───────────────────


class TestNoDate:
    def test_no_date_returns_none(self):
        assert extract_date("Need to clean oil from prop") is None

    def test_empty_content(self):
        assert extract_date("") is None

    def test_none_content(self):
        assert extract_date(None) is None

    def test_just_a_number(self):
        """Plain numbers shouldn't trigger date extraction."""
        assert extract_date("I need 15 screws from the hardware store") is None

    def test_phone_number_no_false_positive(self):
        """Phone numbers like 555-1234 shouldn't trigger."""
        assert extract_date("Sarah's phone is 555-1234") is None

    def test_invalid_date_feb_30(self):
        assert extract_date("Event on February 30th") is None

    def test_invalid_month_zero(self):
        assert extract_date("Event on 0/15/2026") is None

    def test_invalid_day_zero(self):
        assert extract_date("Event on Feb 0th") is None


# ── Date extraction: title generation ─────────────────────────────


class TestTitle:
    def test_title_from_content(self):
        result = extract_date("Bring trees inside before frost Feb 2nd")
        assert result is not None
        assert result["title"]  # non-empty
        assert len(result["title"]) <= 63  # 60 + "..." buffer

    def test_title_strips_frontmatter(self):
        content = "---\ntitle: My Note\n---\nDentist Feb 5th"
        result = extract_date(content)
        assert result is not None
        assert "---" not in result["title"]


# ── Summary validation ────────────────────────────────────────────


class TestSummaryValidation:
    def test_valid_summary_passes(self):
        content = "I need to bring the trees inside before the frost hits"
        summary = "Reminder to bring trees inside before frost"
        assert validate_summary(content, summary) == summary

    def test_contaminated_summary_replaced(self):
        content = "I need to bring the trees inside before the frost hits"
        summary = "Schedule a dentist appointment for next Tuesday"
        result = validate_summary(content, summary)
        assert result != summary
        # Result should come from the content
        assert "trees" in result.lower() or "frost" in result.lower() or "bring" in result.lower()

    def test_empty_summary_replaced(self):
        content = "Buy groceries from the store"
        result = validate_summary(content, "")
        assert result  # non-empty
        assert result != ""

    def test_none_summary_replaced(self):
        content = "Buy groceries from the store"
        result = validate_summary(content, None)
        assert result  # non-empty

    def test_whitespace_summary_replaced(self):
        content = "Buy groceries from the store"
        result = validate_summary(content, "   ")
        assert result.strip()

    def test_empty_content_keeps_summary(self):
        summary = "Some summary"
        assert validate_summary("", summary) == summary

    def test_derived_summary_max_length(self):
        content = "x " * 200 + " Feb 2nd"
        # No date in this test, just checking summary derivation
        result = validate_summary(content, None)
        assert len(result) <= 120

    def test_derived_summary_first_sentence(self):
        content = "Buy milk from the store. Also get eggs. And bread."
        result = validate_summary(content, None)
        assert result == "Buy milk from the store."
