"""Tests for build_subject — the function that generates the email subject line.

The subject line adapts to the mix:
  1 GRE only         -> "GRE Word of the Day: <word>"
  Multiple GRE only  -> "GRE Words of the Day: <w1>, <w2>, ..."
  GRE + Difficult    -> "GRE & Difficult Words of the Day: ..."
  Difficult only     -> "Difficult Word of the Day: ..."

These are also pure functions: input is a list of (word, source) tuples,
output is a string. Easy to test exhaustively.
"""

from word_of_the_day import SOURCE_DIFFICULT, SOURCE_GRE, build_subject


class TestBuildSubject:
    def test_single_gre_word(self):
        s = build_subject([("prolix", SOURCE_GRE)])
        assert s == "GRE Word of the Day: prolix"

    def test_two_gre_words(self):
        # Edge case: pick_words_mixed never produces this (it always adds
        # a Difficult word at count >= 2), but build_subject should still
        # handle it correctly for robustness.
        s = build_subject([("foo", SOURCE_GRE), ("bar", SOURCE_GRE)])
        assert s == "GRE Words of the Day: foo, bar"

    def test_one_gre_plus_one_difficult(self):
        s = build_subject([("foo", SOURCE_GRE), ("bar", SOURCE_DIFFICULT)])
        assert s.startswith("GRE & Difficult Words of the Day:")
        assert "foo" in s
        assert "bar" in s

    def test_two_gre_plus_one_difficult(self):
        s = build_subject([
            ("alpha", SOURCE_GRE),
            ("beta", SOURCE_GRE),
            ("gamma", SOURCE_DIFFICULT),
        ])
        assert s.startswith("GRE & Difficult Words of the Day:")
        for word in ("alpha", "beta", "gamma"):
            assert word in s

    def test_single_difficult_word(self):
        # Edge case: someone manually constructs a Difficult-only pick.
        s = build_subject([("borborygmus", SOURCE_DIFFICULT)])
        assert s == "Difficult Word of the Day: borborygmus"

    def test_word_order_in_subject_matches_input_order(self):
        # The subject lists words in the order they were picked, which is the
        # order they'll appear in the email body. Order matters for matching.
        s = build_subject([
            ("alpha", SOURCE_GRE),
            ("beta", SOURCE_GRE),
            ("gamma", SOURCE_DIFFICULT),
        ])
        # alpha appears before beta in the string, which appears before gamma.
        i_alpha = s.index("alpha")
        i_beta = s.index("beta")
        i_gamma = s.index("gamma")
        assert i_alpha < i_beta < i_gamma
