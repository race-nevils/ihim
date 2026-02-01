"""Tests for deterministic fallback: date extraction and summary validation."""
import pytest
from datetime import date
from unittest.mock import patch

from datetime import timedelta
from handlers.fallback import extract_date, validate_summary, detect_calendar_by_keywords


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


# ── Keyword detection: strong triggers ───────────────────────────


class TestKeywordStrongTriggers:
    @patch("handlers.fallback.date")
    def test_tomorrow(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Call dentist tomorrow morning")
        assert result is not None
        assert result["is_event"] is True
        assert result["date"] == "2026-02-01"
        assert result["time"] == "09:00"

    @patch("handlers.fallback.date")
    def test_tonight(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Bring trees inside tonight before dark")
        assert result is not None
        assert result["date"] == "2026-01-31"
        assert result["time"] == "20:00"
        assert result["all_day"] is False

    @patch("handlers.fallback.date")
    def test_day_after_tomorrow(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Pick up package day after tomorrow")
        assert result is not None
        assert result["date"] == "2026-02-02"

    @patch("handlers.fallback.date")
    def test_next_monday(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)  # Saturday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Team meeting next Monday")
        assert result is not None
        assert result["date"] == "2026-02-09"  # Always >= 7 days away

    @patch("handlers.fallback.date")
    def test_this_friday(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 28)  # Wednesday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Submit report this Friday")
        assert result is not None
        assert result["date"] == "2026-01-30"

    @patch("handlers.fallback.date")
    def test_this_weekend(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 28)  # Wednesday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Go hiking this weekend")
        assert result is not None
        assert result["date"] == "2026-01-31"  # Saturday

    @patch("handlers.fallback.date")
    def test_next_month(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Start project next month")
        assert result is not None
        assert result["date"] == "2026-02-01"

    @patch("handlers.fallback.date")
    def test_scheduling_noun_appointment(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Dentist appointment at noon")
        assert result is not None
        assert result["date"] == "2026-02-01"  # Default: tomorrow
        assert result["time"] == "12:00"

    @patch("handlers.fallback.date")
    def test_scheduling_noun_flight(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Book a flight to Denver")
        assert result is not None
        assert result["is_event"] is True

    @patch("handlers.fallback.date")
    def test_deadline_by_friday(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 28)  # Wednesday
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Report due Friday")
        assert result is not None

    @patch("handlers.fallback.date")
    def test_deadline_by_eod(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Submit expense report by EOD")
        assert result is not None
        assert result["date"] == "2026-01-31"

    @patch("handlers.fallback.date")
    def test_end_of_month(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 15)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Pay rent end of the month")
        assert result is not None
        assert result["date"] == "2026-01-31"


# ── Keyword detection: medium triggers ───────────────────────────


class TestKeywordMediumTriggers:
    @patch("handlers.fallback.date")
    def test_morning_with_verb(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Call the plumber morning")
        assert result is not None
        assert result["time"] == "09:00"

    def test_morning_without_verb_returns_none(self):
        """Time-of-day without action verb should NOT trigger."""
        result = detect_calendar_by_keywords("What a beautiful morning")
        assert result is None

    @patch("handlers.fallback.date")
    def test_after_lunch_with_verb(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Meet Sarah after lunch")
        assert result is not None
        assert result["time"] == "13:00"

    @patch("handlers.fallback.date")
    def test_in_3_days(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Finish the report in 3 days")
        assert result is not None
        assert result["date"] == "2026-02-03"

    @patch("handlers.fallback.date")
    def test_in_2_weeks(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Review proposal in 2 weeks")
        assert result is not None
        assert result["date"] == "2026-02-14"

    @patch("handlers.fallback.date")
    def test_in_a_few_days_with_verb(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Call them back in a few days")
        assert result is not None
        assert result["date"] == "2026-02-03"


# ── Keyword detection: contextual triggers ───────────────────────


class TestKeywordContextualTriggers:
    @patch("handlers.fallback.date")
    def test_soon_with_verb_and_future_marker(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("I need to call the dentist soon")
        assert result is not None
        assert result["date"] == "2026-02-01"

    def test_soon_alone_returns_none(self):
        """'Soon' without verb + future marker should NOT trigger."""
        result = detect_calendar_by_keywords("The movie is coming out soon")
        assert result is None

    @patch("handlers.fallback.date")
    def test_asap_with_verb_and_future_marker(self, mock_date):
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("I need to submit the form asap")
        assert result is not None

    def test_later_alone_returns_none(self):
        """'Later' without verb + future marker should NOT trigger."""
        result = detect_calendar_by_keywords("I'll think about that later")
        assert result is None


# ── Keyword detection: negation / retrospective ──────────────────


class TestKeywordNegation:
    def test_remember_when_returns_none(self):
        result = detect_calendar_by_keywords("Remember when we had that meeting tomorrow")
        assert result is None

    def test_used_to_returns_none(self):
        result = detect_calendar_by_keywords("I used to have an appointment every morning")
        assert result is None

    def test_cancel_returns_none(self):
        result = detect_calendar_by_keywords("Cancel the meeting tomorrow")
        assert result is None

    def test_wont_returns_none(self):
        result = detect_calendar_by_keywords("I won't make it to the appointment tomorrow")
        assert result is None

    def test_past_tense_dominant_returns_none(self):
        result = detect_calendar_by_keywords("We had a meeting about the morning shift")
        assert result is None

    def test_the_other_day_returns_none(self):
        result = detect_calendar_by_keywords("The other day I had an appointment")
        assert result is None


# ── Keyword detection: edge cases ────────────────────────────────


class TestKeywordEdgeCases:
    def test_empty_string(self):
        assert detect_calendar_by_keywords("") is None

    def test_none_input(self):
        assert detect_calendar_by_keywords(None) is None

    def test_whitespace_only(self):
        assert detect_calendar_by_keywords("   ") is None

    def test_no_keywords(self):
        assert detect_calendar_by_keywords("The sky is blue and water is wet") is None

    def test_result_dict_shape(self):
        """Result should have the same keys as extract_date()."""
        result = detect_calendar_by_keywords("Dentist appointment tomorrow")
        assert result is not None
        assert "is_event" in result
        assert "title" in result
        assert "date" in result
        assert "time" in result
        assert "all_day" in result

    def test_title_not_empty(self):
        result = detect_calendar_by_keywords("Call dentist tomorrow")
        assert result is not None
        assert result["title"]
        assert len(result["title"]) > 0

    def test_frontmatter_stripped(self):
        content = "---\ntitle: Test Note\n---\nBring trees inside tomorrow"
        result = detect_calendar_by_keywords(content)
        assert result is not None
        assert "---" not in result["title"]


# ── Bare time-of-day regex (extract_date secondary check) ────────


class TestBareTimeOfDay:
    def test_bare_morning_with_date(self):
        result = extract_date("Feb 2nd morning")
        assert result is not None
        assert result["date"].endswith("-02-02")
        assert result["time"] == "09:00"
        assert result["all_day"] is False

    def test_bare_afternoon_with_date(self):
        result = extract_date("Feb 10th afternoon")
        assert result is not None
        assert result["date"].endswith("-02-10")
        assert result["time"] == "14:00"
        assert result["all_day"] is False

    def test_bare_evening_with_date(self):
        result = extract_date("March 5th evening")
        assert result is not None
        assert result["date"].endswith("-03-05")
        assert result["time"] == "18:00"
        assert result["all_day"] is False

    def test_in_the_morning_still_works(self):
        """Existing 'in the morning' pattern must not regress."""
        result = extract_date("Bring trees inside Feb 2nd in the morning")
        assert result is not None
        assert result["time"] == "09:00"
        assert result["all_day"] is False

    def test_bare_morning_no_date_returns_none(self):
        """Bare 'morning' without an explicit date should return None."""
        assert extract_date("tomorrow morning") is None

    @patch("handlers.fallback.date")
    def test_december_edge_next_month(self, mock_date):
        """Next month from December should be January of next year."""
        mock_date.today.return_value = date(2026, 12, 15)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Start fresh next month")
        assert result is not None
        assert result["date"] == "2027-01-01"

    @patch("handlers.fallback.date")
    def test_end_of_december(self, mock_date):
        """End of month in December should be Dec 31."""
        mock_date.today.return_value = date(2026, 12, 15)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        result = detect_calendar_by_keywords("Finish project end of the month")
        assert result is not None
        assert result["date"] == "2026-12-31"


# ── Keyword detection: integration with classify ─────────────────


class TestKeywordIntegration:
    @patch("handlers.fallback.date")
    def test_keyword_fallback_catches_what_regex_misses(self, mock_date):
        """Content with no explicit date but temporal language should be caught."""
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        # This has no explicit date — regex returns None
        content = "Bring trees inside before dark tonight"
        assert extract_date(content) is None
        # But keyword detection catches it
        result = detect_calendar_by_keywords(content)
        assert result is not None
        assert result["is_event"] is True
        assert result["date"] == "2026-01-31"

    @patch("handlers.fallback.date")
    def test_regex_still_preferred_over_keywords(self, mock_date):
        """Content with explicit date should be caught by regex, not keywords."""
        mock_date.today.return_value = date(2026, 1, 31)
        mock_date.side_effect = lambda *args, **kw: date(*args, **kw)
        content = "Dentist appointment Feb 4th at 3pm"
        regex_result = extract_date(content)
        assert regex_result is not None
        assert regex_result["date"] == "2026-02-04"
