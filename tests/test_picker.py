"""Tests for the word-picking logic.

Both pick_words and pick_words_mixed are PURE functions — they take inputs and
return outputs with no side effects (no file I/O, no network, no clock). Pure
functions are dramatically easier to test: you just pick inputs and assert on
outputs. No mocking, no fixtures, no setup/teardown.

Because the picker uses random.shuffle internally, we can't predict exactly
which words come out. So instead of asserting "pick X returns ['foo']", we
assert PROPERTIES that must hold for any valid pick — length, no duplicates,
no avoid-set leakage, etc. This is called PROPERTY-BASED TESTING and it's
much more robust than seeded "magic value" tests.
"""

import random

import pytest

from word_of_the_day import (
    SOURCE_DIFFICULT,
    SOURCE_GRE,
    pick_words,
    pick_words_mixed,
)


# ---------------------------------------------------------------------------
# pick_words — the single-pool picker
# ---------------------------------------------------------------------------

class TestPickWords:
    def test_returns_requested_count(self):
        pool = ["a", "b", "c", "d", "e", "f", "g"]
        result = pick_words(pool, avoid=set(), count=3)
        assert len(result) == 3

    def test_returns_no_duplicates(self):
        pool = ["a", "b", "c", "d", "e"]
        result = pick_words(pool, avoid=set(), count=5)
        assert len(set(result)) == len(result)

    def test_avoids_words_in_avoid_set(self):
        pool = ["a", "b", "c", "d", "e"]
        avoid = {"a", "b"}
        # Run a few times because picking is random — if "a" or "b" ever shows
        # up that's a bug. With pool size 5, avoid size 2, count 3, the picker
        # has exactly enough candidates and must use {c, d, e}.
        for _ in range(20):
            result = pick_words(pool, avoid, count=3)
            assert set(result) == {"c", "d", "e"}

    def test_falls_back_to_full_pool_when_candidates_run_out(self):
        # If the avoid set is so large there aren't enough candidates left,
        # the picker resets and uses the full pool. Otherwise we'd send empty.
        pool = ["a", "b", "c"]
        avoid = {"a", "b", "c"}
        result = pick_words(pool, avoid, count=2)
        assert len(result) == 2
        assert all(w in pool for w in result)

    def test_returns_only_words_from_pool(self):
        pool = ["a", "b", "c"]
        for _ in range(20):
            result = pick_words(pool, avoid=set(), count=2)
            assert all(w in pool for w in result)


# ---------------------------------------------------------------------------
# pick_words_mixed — the GRE + Difficult mix
# ---------------------------------------------------------------------------
# Mix rules:
#   count == 1 -> 1 GRE
#   count == 2 -> 1 GRE + 1 Difficult
#   count >= 3 -> (count - 1) GRE + 1 Difficult
# The difficult word always comes LAST in the returned list.

GRE_POOL = [f"gre{i}" for i in range(20)]
DIFFICULT_POOL = [f"diff{i}" for i in range(20)]


def _sources(picks):
    return [s for _, s in picks]


class TestPickWordsMixed:
    def test_count_1_yields_one_gre(self):
        picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), 1)
        assert len(picks) == 1
        assert _sources(picks) == [SOURCE_GRE]

    def test_count_2_yields_one_gre_one_difficult(self):
        picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), 2)
        assert len(picks) == 2
        assert _sources(picks) == [SOURCE_GRE, SOURCE_DIFFICULT]

    def test_count_3_yields_two_gre_one_difficult(self):
        picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), 3)
        assert len(picks) == 3
        assert _sources(picks) == [SOURCE_GRE, SOURCE_GRE, SOURCE_DIFFICULT]

    def test_count_5_yields_four_gre_one_difficult(self):
        picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), 5)
        assert len(picks) == 5
        assert _sources(picks) == [SOURCE_GRE] * 4 + [SOURCE_DIFFICULT]

    def test_difficult_word_comes_last(self):
        # Whatever the count (>= 2), the difficult word is always the last item.
        for count in (2, 3, 4, 5):
            picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), count)
            assert picks[-1][1] == SOURCE_DIFFICULT
            for word, source in picks[:-1]:
                assert source == SOURCE_GRE

    def test_words_come_from_correct_pools(self):
        picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), 3)
        gre_words = [w for w, s in picks if s == SOURCE_GRE]
        diff_words = [w for w, s in picks if s == SOURCE_DIFFICULT]
        for w in gre_words:
            assert w in GRE_POOL
        for w in diff_words:
            assert w in DIFFICULT_POOL

    def test_no_duplicates_across_sources(self):
        # If GRE and Difficult pools share a word, the same word shouldn't
        # show up twice (once with each source) in a single pick.
        shared_pool_gre = ["alpha", "beta", "gamma"]
        shared_pool_diff = ["beta", "gamma", "delta"]
        for _ in range(20):
            picks = pick_words_mixed(shared_pool_gre, shared_pool_diff, set(), 2)
            words = [w for w, _ in picks]
            assert len(set(words)) == 2

    def test_avoid_set_excludes_words(self):
        avoid = {f"gre{i}" for i in range(18)}  # leave only gre18, gre19
        # Picker for the GRE half should land on gre18 / gre19, never the avoided ones.
        for _ in range(20):
            picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, avoid, 3)
            gre_words = [w for w, s in picks if s == SOURCE_GRE]
            for w in gre_words:
                assert w in {"gre18", "gre19"}

    def test_zero_or_negative_count_treated_as_one(self):
        # Defensive: caller might pass 0 by accident. Don't crash.
        picks = pick_words_mixed(GRE_POOL, DIFFICULT_POOL, set(), 0)
        assert len(picks) == 1
        assert picks[0][1] == SOURCE_GRE
