"""Tests for the kids'-content filter and fallback library.

Pure functions only -- no network, no hardware. generate() itself (the actual
Anthropic call) is exercised manually per the plan's verification checklist,
not here.
"""

from __future__ import annotations

import pytest

from ohbot_kit import expression as ex
from ohbot_kit import kids_content as kc


def _content(*texts: str) -> dict:
    return {"segments": [{"text": t, "expression": "happy"} for t in texts]}


class TestFilterContent:
    def test_clean_text_passes(self) -> None:
        assert kc.filter_content(_content("A happy little bunny hops down the lane.")) == []

    def test_blocklisted_whole_word_is_reported(self) -> None:
        problems = kc.filter_content(_content("The scary monster went home."))
        assert len(problems) == 1
        assert "scary" in problems[0]
        assert "monster" in problems[0]

    def test_substring_does_not_false_positive(self) -> None:
        """REGRESSION target: "classic" must not trip on the blocked word "class"
        (which isn't even blocked) -- more importantly "scar" substrings like
        "scarf" must not trip on "scary"."""
        assert kc.filter_content(_content("She wore a soft scarf and a classic hat.")) == []

    def test_multiple_segments_checked_independently(self) -> None:
        content = _content(
            "A happy little bunny hops along.",
            "Then a scary ghost appeared!",
            "The end, everyone smiled.",
        )
        problems = kc.filter_content(content)
        assert len(problems) == 1
        assert "segment 2" in problems[0]


class TestFallbackLibrary:
    @pytest.mark.parametrize("content_type", sorted(kc.FALLBACK_LIBRARY))
    def test_each_type_has_three_to_four_items(self, content_type: str) -> None:
        items = kc.FALLBACK_LIBRARY[content_type]
        assert 3 <= len(items) <= 4

    @pytest.mark.parametrize("content_type", sorted(kc.FALLBACK_LIBRARY))
    def test_every_item_has_valid_segments(self, content_type: str) -> None:
        for item in kc.FALLBACK_LIBRARY[content_type]:
            segments = item["segments"]
            assert 3 <= len(segments) <= 5
            for seg in segments:
                assert seg["expression"] in kc.EXPRESSIONS
                assert seg["text"].strip()

    @pytest.mark.parametrize("content_type", sorted(kc.FALLBACK_LIBRARY))
    def test_get_fallback_returns_valid_item(self, content_type: str) -> None:
        item = kc.get_fallback(content_type)
        assert item in kc.FALLBACK_LIBRARY[content_type]

    def test_unknown_content_type_falls_back_to_joke(self) -> None:
        assert kc.get_fallback("not_a_real_type") in kc.FALLBACK_LIBRARY["joke"]


def test_expressions_are_a_subset_of_known_poses() -> None:
    """The app can only ever ask the robot to express() one of EXPRESSIONS, so
    every one of those tags must exist in ohbot_kit.expression.POSES -- this is
    exactly the test that would catch a forgotten `silly`/`sleepy` addition."""
    assert set(kc.EXPRESSIONS) <= set(ex.POSES)
