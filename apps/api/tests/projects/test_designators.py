import re
import unicodedata

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from support.bom import (
    designator_sets,
    designator_spellings,
    designators,
    joined,
    list_items,
    list_spellings,
    prefixes,
    runs_of,
)
from wiredex.projects.domain.designators import (
    MAX_DESIGNATOR_NUMBER,
    MAX_DESIGNATORS,
    Designator,
    Designators,
)
from wiredex.projects.domain.errors import (
    InvalidDesignatorError,
    InvalidDesignatorRangeError,
    RepeatedDesignatorError,
    TooManyDesignatorsError,
)


class TestDesignator:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [("r01", "R1"), ("\uff32\uff11", "R1"), (" c12 ", "C12"), ("R1", "R1"), ("sw0003", "SW3")],
    )
    def test_reads_every_spelling_as_its_stored_form(self, text: str, expected: str) -> None:
        assert str(Designator.parse(text)) == expected

    def test_r01_and_r1_are_one_designator(self) -> None:
        assert Designator.parse("r01") == Designator.parse("R1") == Designator("R", 1)

    @pytest.mark.parametrize(
        "text", ["U1A", "U1.2", "R0", "R10000", "ABCDEFGHI1", "1R", "Ω1", "R", "", "R 1", "R-1"]
    )
    def test_refuses_anything_else_naming_it(self, text: str) -> None:
        with pytest.raises(InvalidDesignatorError) as refused:
            Designator.parse(text)
        assert refused.value.item == text
        assert repr(text) in str(refused.value)

    def test_accepts_eight_letters_and_the_largest_number(self) -> None:
        assert str(Designator.parse("abcdefgh9999")) == "ABCDEFGH9999"

    def test_leading_zeros_never_make_a_number_too_large(self) -> None:
        assert Designator.parse("R" + "0" * 5000 + "7") == Designator("R", 7)

    def test_thousands_of_digits_are_refused_not_crashed_on(self) -> None:
        with pytest.raises(InvalidDesignatorError):
            Designator.parse("R" + "9" * 5000)

    @pytest.mark.parametrize(("letters", "number"), [("r", 1), ("R", 0), ("R1", 1), ("", 3)])
    def test_is_refused_built_from_parts_outside_its_form(self, letters: str, number: int) -> None:
        with pytest.raises(InvalidDesignatorError):
            Designator(letters, number)

    def test_orders_by_letters_and_then_number(self) -> None:
        texts = ["RN1", "R10", "C1", "R2", "R1"]
        ordered = sorted(Designator.parse(text) for text in texts)
        assert [str(designator) for designator in ordered] == ["C1", "R1", "R2", "R10", "RN1"]


class TestDesignatorsParse:
    @pytest.mark.parametrize(
        "text", ["R1-4", "R1 – R4", "R1—R4", "r1-r4", "R1 -\t4", "R1,R2 R3,R4"]
    )
    def test_reads_a_range_in_every_spelling_alike(self, text: str) -> None:
        assert Designators.parse(text).text() == "R1–R4"

    @pytest.mark.parametrize("text", ["", "   ", ", ,", "\n"])
    def test_blank_text_is_no_designators(self, text: str) -> None:
        assert Designators.parse(text) == Designators.none()

    @pytest.mark.parametrize(
        ("text", "reason"),
        [
            ("R4-R1", "run upwards"),
            ("R3-R3", "run upwards"),
            ("R1-C4", "one prefix"),
            ("R9-2", "run upwards"),
        ],
    )
    def test_refuses_a_range_that_doesnt_run_upwards_in_one_prefix(
        self, text: str, reason: str
    ) -> None:
        with pytest.raises(InvalidDesignatorRangeError, match=reason) as refused:
            Designators.parse(f"C1, {text}")
        assert refused.value.item == text

    @pytest.mark.parametrize("text", ["R1-", "R1-4-6", "U1A", "R1;R2", "-R4", "R1-0", "R1-C"])
    def test_refuses_an_item_that_is_neither_naming_it(self, text: str) -> None:
        with pytest.raises(InvalidDesignatorError) as refused:
            Designators.parse(f"C1, {text}")
        assert refused.value.item == text

    @pytest.mark.parametrize(
        ("text", "repeat"), [("R1, R1", "R1"), ("R1-R3, R2", "R2"), ("R2, R1-3", "R2")]
    )
    def test_refuses_a_designator_named_twice_naming_it(self, text: str, repeat: str) -> None:
        with pytest.raises(RepeatedDesignatorError, match=f"{repeat} is named twice") as refused:
            Designators.parse(text)
        assert refused.value.item == repeat

    def test_holds_256_designators_and_refuses_257(self) -> None:
        assert len(Designators.parse("R1-256")) == MAX_DESIGNATORS
        with pytest.raises(TooManyDesignatorsError, match="at most 256"):
            Designators.parse("R1-256, C1")
        with pytest.raises(TooManyDesignatorsError):
            Designators.parse("C1, R1-256")

    def test_a_huge_range_is_refused_as_too_many(self) -> None:
        with pytest.raises(TooManyDesignatorsError):
            Designators.parse(f"R1–R{MAX_DESIGNATOR_NUMBER}")


class TestDesignators:
    @pytest.mark.parametrize(
        ("text", "canonical"),
        [
            ("R7, R3, c1, R2, R1", "C1, R1–R3, R7"),
            ("R2 R1", "R1, R2"),
            ("R4-6, R2, R1", "R1, R2, R4–R6"),
            ("RN1, R1, R10, R2", "R1, R2, R10, RN1"),
        ],
    )
    def test_writes_the_canonical_text(self, text: str, canonical: str) -> None:
        assert Designators.parse(text).text() == canonical

    def test_none_writes_nothing(self) -> None:
        assert Designators.none().text() == ""
        assert len(Designators.none()) == 0

    def test_of_sorts_and_refuses_a_repeat(self) -> None:
        r2, r1 = Designator("R", 2), Designator("R", 1)
        assert tuple(Designators.of([r2, r1])) == (r1, r2)
        with pytest.raises(RepeatedDesignatorError, match="R2"):
            Designators.of([r2, r1, r2])

    def test_of_refuses_more_than_256(self) -> None:
        with pytest.raises(TooManyDesignatorsError):
            Designators.of(Designator("R", number) for number in range(1, 258))

    def test_answers_whether_it_holds_a_designator(self) -> None:
        held = Designators.parse("R1-3")
        assert Designator("R", 2) in held
        assert Designator("R", 4) not in held
        assert "R2" not in held

    def test_two_spellings_of_one_list_are_equal(self) -> None:
        assert Designators.parse("r3 r1 r2") == Designators.parse("R1-3")


# --- Property 2: a designator is exactly its grammar, and its text is a fixpoint ------------

_GRAMMAR = re.compile(r"([A-Za-z]{1,8})([0-9]+)")
_TRICKY = "Rr0123456789 \t\u3000\uff32\uff11\u03a9\u0130AZaz.-_–"  # fullwidth R1, Ω, İ


def _is_designator(text: str) -> bool:
    read = _GRAMMAR.fullmatch(unicodedata.normalize("NFKC", text).strip())
    return read is not None and 1 <= int(read.group(2)) <= MAX_DESIGNATOR_NUMBER


@given(
    text=st.text() | st.text(alphabet=_TRICKY, max_size=14),
    designator=designators,
    data=st.data(),
)
def test_a_designator_is_exactly_its_grammar(
    text: str, designator: Designator, data: st.DataObject
) -> None:
    """Property 2: a designator is exactly its grammar, and its text is a fixpoint.

    For any text, Designator.parse accepts it if and only if, after NFKC and trimming, it is 1
    to 8 ASCII letters followed by ASCII digits whose value is from 1 to 9999, and a refused
    text is the item its refusal names. An accepted designator's text is its letters
    upper-cased and its number without leading zeros; parsing that text gives an equal
    designator; and every other spelling of it, in another case, with leading zeros, in
    fullwidth forms or with spaces around it, parses equal to it.

    **Validates: Requirements 3.1, 3.2**
    """
    if _is_designator(text):
        parsed = Designator.parse(text)
        assert Designator.parse(str(parsed)) == parsed
    else:
        with pytest.raises(InvalidDesignatorError) as refused:
            Designator.parse(text)
        assert refused.value.item == unicodedata.normalize("NFKC", text).strip()

    assert str(designator) == f"{designator.letters}{designator.number}"
    assert Designator.parse(str(designator)) == designator
    spelling = data.draw(designator_spellings(designator))
    padding = data.draw(st.sampled_from(["", " ", "\t", "　"]))
    assert Designator.parse(f"{padding}{spelling}{padding}") == designator


# --- Property 3: canonical text reads back as the same designators ------------------------


# A set of designators takes a while to draw, and a busy machine trips the slow-input check.
@settings(suppress_health_check=[HealthCheck.too_slow])
@given(wanted=designator_sets())
def test_canonical_text_reads_back_as_the_same_designators(
    wanted: frozenset[Designator],
) -> None:
    """Property 3: canonical text reads back as the same designators.

    For any set of at most 256 distinct designators, the canonical text of
    Designators.of(set) lists them ordered by letters and then number, writes as first–last,
    with an en dash, exactly the maximal runs of three or more consecutive numbers of one
    prefix and nothing else, and reading it with Designators.parse gives the same designators.

    **Validates: Requirements 3.7, 3.8**
    """
    held = Designators.of(wanted)
    expected: list[str] = []
    for run in runs_of(wanted):
        if len(run) >= 3:
            expected.append(f"{run[0]}–{run[-1]}")
        else:
            expected.extend(str(designator) for designator in run)
    assert held.text() == ", ".join(expected)
    assert tuple(held) == tuple(sorted(wanted))
    assert Designators.parse(held.text()) == held


# --- Property 4: any spelling of a list reads the same --------------------------------------


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(wanted=designator_sets(), data=st.data())
def test_any_spelling_of_a_list_reads_the_same(
    wanted: frozenset[Designator], data: st.DataObject
) -> None:
    """Property 4: any spelling of a list reads the same.

    For any set of at most 256 distinct designators and any way of writing it (items in any
    order, separated by any mix of commas and whitespace, runs of any length written as ranges
    joined by -, – or — with or without spaces around the dash, their ends in full or in the
    short form R1-4), Designators.parse reads exactly that set. Adding to such a text a
    designator it already names, directly or inside a range, is refused naming a designator
    the text names twice; a range whose end isn't above its start, or whose ends' letters
    differ, is refused naming that range; and a text naming more than 256 designators is
    refused.

    **Validates: Requirements 3.3, 3.4, 3.5, 3.6**
    """
    items = data.draw(list_items(wanted))
    assert set(Designators.parse(data.draw(joined(items)))) == wanted

    if wanted:
        repeat = data.draw(st.sampled_from(sorted(wanted)))
        at = data.draw(st.integers(0, len(items)))
        spelled = data.draw(designator_spellings(repeat))
        with pytest.raises(RepeatedDesignatorError) as refused:
            Designators.parse(data.draw(joined([*items[:at], spelled, *items[at:]])))
        assert refused.value.item == str(repeat)

    bad_range = data.draw(_bad_ranges())
    at = data.draw(st.integers(0, len(items)))
    with pytest.raises(InvalidDesignatorRangeError) as refused_range:
        Designators.parse(data.draw(joined([*items[:at], bad_range, *items[at:]])))
    assert refused_range.value.item == bad_range


@given(data=st.data())
def test_a_list_naming_more_than_256_designators_is_refused(data: st.DataObject) -> None:
    """Property 4, its last clause: however it is written, a list naming more than 256
    designators is refused.

    **Validates: Requirements 3.6**
    """
    # One long run past the cap and a few others: drawn run by run, the smallest set Hypothesis
    # could shrink to would take hundreds of draws.
    letters = data.draw(prefixes)
    size = data.draw(st.integers(MAX_DESIGNATORS + 1, 400))
    start = data.draw(st.integers(1, MAX_DESIGNATOR_NUMBER - size + 1))
    run = {Designator(letters, number) for number in range(start, start + size)}
    wanted = run | data.draw(designator_sets(max_size=20))
    with pytest.raises(TooManyDesignatorsError):
        Designators.parse(data.draw(list_spellings(wanted)))


@st.composite
def _bad_ranges(draw: st.DrawFn) -> str:
    """A range whose end isn't above its start, or whose ends' letters differ."""
    start = draw(designators)
    if draw(st.booleans()):
        return f"{start}-{draw(st.integers(1, start.number))}"
    end = draw(designators.filter(lambda end: end.letters != start.letters))
    return f"{start}-{end}"
