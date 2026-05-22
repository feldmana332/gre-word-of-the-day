"""Tests for recent_words — the function that computes the avoid-set.

`recent_words(state, days)` looks at history entries and returns the set of
words sent within the last `days` days. This is what stops the picker from
re-using the same word two days in a row.

This test file teaches one extra pattern: we use `date.today()` in tests via
RELATIVE OFFSETS. We never write "2025-11-14" into a test — that would break
the moment time moves on. Instead, "today minus N days" stays correct forever.
"""

from datetime import date, timedelta

from word_of_the_day import recent_words


def _days_ago(n):
    """Helper: ISO date string for N days before today."""
    return (date.today() - timedelta(days=n)).isoformat()


class TestRecentWords:
    def test_empty_state_returns_empty_set(self):
        assert recent_words({}, days=30) == set()

    def test_state_with_no_history_key_returns_empty(self):
        assert recent_words({"some_other_key": "value"}, days=30) == set()

    def test_words_within_window_are_included(self):
        state = {
            "history": [
                {"date": _days_ago(1), "words": ["foo", "bar"]},
                {"date": _days_ago(5), "words": ["baz"]},
            ]
        }
        assert recent_words(state, days=30) == {"foo", "bar", "baz"}

    def test_words_outside_window_are_excluded(self):
        state = {
            "history": [
                {"date": _days_ago(100), "words": ["ancient"]},
                {"date": _days_ago(2), "words": ["recent"]},
            ]
        }
        assert recent_words(state, days=30) == {"recent"}

    def test_words_exactly_at_window_boundary_are_included(self):
        # The cutoff is `today - days`. An entry on exactly that date should
        # still count as "recent" — within the window, not past it.
        state = {"history": [{"date": _days_ago(30), "words": ["edge"]}]}
        assert recent_words(state, days=30) == {"edge"}

    def test_malformed_entries_are_skipped_not_crashed(self):
        # If state.json gets corrupted somehow, we don't want one bad entry
        # to take down the whole pipeline. Skip what we can't parse.
        state = {
            "history": [
                {"date": "not-a-date", "words": ["bad"]},
                {"words": ["missing-date-key"]},
                {"date": _days_ago(1), "words": ["good"]},
            ]
        }
        assert recent_words(state, days=30) == {"good"}

    def test_returns_a_set_not_a_list(self):
        # Type matters: the picker does `pool - avoid` style filtering and
        # relies on set membership being O(1).
        state = {"history": [{"date": _days_ago(1), "words": ["a", "b"]}]}
        result = recent_words(state, days=30)
        assert isinstance(result, set)

    def test_duplicates_across_entries_collapse(self):
        state = {
            "history": [
                {"date": _days_ago(1), "words": ["foo"]},
                {"date": _days_ago(2), "words": ["foo", "bar"]},
            ]
        }
        assert recent_words(state, days=30) == {"foo", "bar"}
