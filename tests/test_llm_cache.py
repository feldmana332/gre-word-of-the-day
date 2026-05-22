"""Tests for the LLM example-sentence cache wrapper.

These tests do NOT make real API calls. We use pytest's `monkeypatch` to
replace `generate_example_sentence` with a stub that records its calls.
This lets us verify cache hit/miss behavior, state mutation, and that the
'no api key' path short-circuits without ever touching the SDK.

This is the standard pattern for testing functions that wrap an external
service: substitute the service call, test the wrapper's logic in isolation.
"""

import word_of_the_day


def test_returns_cached_sentence_without_calling_api(monkeypatch):
    calls = []

    def fake_generate(*args, **kwargs):
        calls.append(args)
        return "FAKE SENTENCE"

    monkeypatch.setattr(word_of_the_day, "generate_example_sentence", fake_generate)

    state = {
        "examples": {
            "perfunctory": {
                "sentence": "He gave the report a perfunctory glance and signed it.",
                "model": "claude-haiku-4-5",
                "generated_at": "2026-05-22T00:00:00+00:00",
            }
        }
    }
    result = word_of_the_day.get_or_generate_example(
        "perfunctory", "done as a duty without care", state, "sk-test"
    )
    assert result == "He gave the report a perfunctory glance and signed it."
    assert calls == []  # never called the API


def test_generates_and_caches_on_miss(monkeypatch):
    monkeypatch.setattr(
        word_of_the_day,
        "generate_example_sentence",
        lambda *args, **kwargs: "FRESH SENTENCE",
    )
    state = {}
    result = word_of_the_day.get_or_generate_example(
        "obstreperous", "noisy and difficult to control", state, "sk-test"
    )
    assert result == "FRESH SENTENCE"
    cached = state["examples"]["obstreperous"]
    assert cached["sentence"] == "FRESH SENTENCE"
    assert cached["model"] == word_of_the_day.LLM_MODEL
    assert "generated_at" in cached


def test_missing_api_key_returns_none_without_calling(monkeypatch):
    calls = []
    monkeypatch.setattr(
        word_of_the_day,
        "generate_example_sentence",
        lambda *args, **kwargs: calls.append(args) or "should-not-be-returned",
    )
    state = {}
    assert word_of_the_day.get_or_generate_example("foo", "bar", state, None) is None
    assert word_of_the_day.get_or_generate_example("foo", "bar", state, "") is None
    assert calls == []  # short-circuits before reaching the API call
    assert state == {}   # state untouched


def test_api_failure_does_not_cache(monkeypatch):
    # When the API returns None (network error, rate limit, etc.), the wrapper
    # should NOT cache None — otherwise a transient failure would permanently
    # disable the LLM example for that word.
    monkeypatch.setattr(
        word_of_the_day,
        "generate_example_sentence",
        lambda *args, **kwargs: None,
    )
    state = {}
    result = word_of_the_day.get_or_generate_example("foo", "bar", state, "sk-test")
    assert result is None
    assert state == {"examples": {}}  # no cache entry written


def test_cached_entry_with_empty_sentence_is_regenerated(monkeypatch):
    # Defensive: if state.json somehow has a malformed entry with no sentence
    # (e.g. partial write, manual edit), we should regenerate rather than
    # silently return the empty value.
    monkeypatch.setattr(
        word_of_the_day,
        "generate_example_sentence",
        lambda *args, **kwargs: "REGENERATED",
    )
    state = {"examples": {"foo": {"sentence": "", "model": "old-model"}}}
    result = word_of_the_day.get_or_generate_example("foo", "definition", state, "sk-test")
    assert result == "REGENERATED"
    assert state["examples"]["foo"]["sentence"] == "REGENERATED"


def test_best_definition_extractor():
    entry = {
        "entries": [
            {
                "pos": "adjective",
                "definitions": [
                    {"definition": "Tediously lengthy."},
                    {"definition": "Long-winded."},
                ],
            }
        ]
    }
    assert (
        word_of_the_day._best_definition_for_word(entry)
        == "Tediously lengthy."
    )


def test_best_definition_handles_missing_data():
    assert word_of_the_day._best_definition_for_word({}) == ""
    assert word_of_the_day._best_definition_for_word({"entries": []}) == ""
    assert (
        word_of_the_day._best_definition_for_word(
            {"entries": [{"definitions": []}]}
        )
        == ""
    )
