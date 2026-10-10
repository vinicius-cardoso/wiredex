"""How typed text finds a record: by words, in any order, case aside."""

import pytest

from wiredex.shared_kernel.domain.text import holds_words, words_of


def test_text_is_read_as_lower_cased_words() -> None:
    assert words_of("  M3   Insert ") == ("m3", "insert")
    assert words_of("   ") == ()


@pytest.mark.parametrize(
    "text",
    ["m3", "insert", "m3 insert", "insert m3", "BRASS m3", "4mm heat", "M3 x 4mm Depth"],
)
def test_every_word_must_be_somewhere_in_any_order(text: str) -> None:
    assert holds_words(text, ["M3 x 4mm Depth x 5mm Width Heat In Brass Insert"])


@pytest.mark.parametrize("text", ["m4", "m3 bolt", "insert steel"])
def test_a_word_found_nowhere_rules_the_record_out(text: str) -> None:
    assert not holds_words(text, ["M3 x 4mm Depth x 5mm Width Heat In Brass Insert"])


def test_words_may_be_in_different_fields_and_missing_fields_are_skipped() -> None:
    # A maker and a value, each in its own field.
    assert holds_words("yageo 4k7", ["R 4k7 0805", None, "Yageo"])
    assert not holds_words("yageo 4k7", ["R 4k7 0805", None, None])


def test_text_with_no_word_narrows_nothing() -> None:
    assert holds_words("", ["anything"])
    assert holds_words("   ", [])
