import re
import string
import unicodedata
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.projects.domain.errors import (
    InvalidProjectNameError,
    InvalidRevisionLabelError,
    InvalidSummaryError,
    InvalidTagError,
    InvalidTextError,
    ProjectsError,
    TooManyTagsError,
)
from wiredex.projects.domain.values import (
    MAX_LABEL_LENGTH,
    MAX_PROJECT_NAME_LENGTH,
    MAX_SUMMARY_LENGTH,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    MAX_TEXT_LENGTH,
    Description,
    Notes,
    ProjectName,
    RevisionLabel,
    RevisionStatus,
    Summary,
    Tag,
    Tags,
)


class TestProjectName:
    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert ProjectName("  Weather \t  station \n").value == "Weather station"

    def test_keeps_the_case_it_was_typed_in(self) -> None:
        assert ProjectName("Greenhouse Controller").value == "Greenhouse Controller"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        name = "x" * MAX_PROJECT_NAME_LENGTH
        assert ProjectName(name).value == name
        with pytest.raises(InvalidProjectNameError, match="between 1 and 120 characters"):
            ProjectName(name + "x")

    @pytest.mark.parametrize("text", ["", "   ", "\t\n"])
    def test_blank_is_never_a_name(self, text: str) -> None:
        with pytest.raises(InvalidProjectNameError):
            ProjectName(text)

    def test_two_cases_of_one_name_fold_alike(self) -> None:
        assert ProjectName("Weather Station").fold() == ProjectName("weather station").fold()


@pytest.mark.parametrize("kind", [Description, Notes])
class TestPlainText:
    def test_reads_crlf_and_a_bare_cr_as_a_line_feed(
        self, kind: type[Description] | type[Notes]
    ) -> None:
        assert kind("one\r\ntwo\rthree").value == "one\ntwo\nthree"

    def test_keeps_inner_line_breaks_and_trims_the_ends(
        self, kind: type[Description] | type[Notes]
    ) -> None:
        # Blank lines and indentation inside are the owner's layout.
        assert kind("\n  first\n\n  second  \n\n").value == "first\n\n  second"

    def test_accepts_its_cap_and_refuses_one_character_more(
        self, kind: type[Description] | type[Notes]
    ) -> None:
        text = "x" * MAX_TEXT_LENGTH
        assert kind(text).value == text
        with pytest.raises(InvalidTextError, match="between 1 and 4,000 characters"):
            kind(text + "x")

    def test_the_cap_counts_after_the_ends_are_trimmed(
        self, kind: type[Description] | type[Notes]
    ) -> None:
        text = "x" * MAX_TEXT_LENGTH
        assert kind(f"\n {text} \n").value == text

    @pytest.mark.parametrize("text", ["", "   ", "\r\n\t"])
    def test_blank_is_refused(self, kind: type[Description] | type[Notes], text: str) -> None:
        with pytest.raises(InvalidTextError):
            kind(text)


class TestSummary:
    def test_is_trimmed_and_has_its_whitespace_collapsed(self) -> None:
        assert Summary("  first \n PCB ").value == "first PCB"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        summary = "x" * MAX_SUMMARY_LENGTH
        assert Summary(summary).value == summary
        with pytest.raises(InvalidSummaryError, match="between 1 and 120 characters"):
            Summary(summary + "x")

    @pytest.mark.parametrize("text", ["", "  ", "\n"])
    def test_blank_is_refused(self, text: str) -> None:
        with pytest.raises(InvalidSummaryError):
            Summary(text)


class TestTag:
    @pytest.mark.parametrize(
        "text", ["esp32", "ESP32", " esp32 ", "\uff25\uff33\uff30\uff13\uff12", "\uff25sp32"]
    )
    def test_fullwidth_and_upper_case_spellings_fold_to_one(self, text: str) -> None:
        assert Tag(text) == Tag("esp32")

    def test_collapses_inner_whitespace_to_one_space(self) -> None:
        assert Tag("  Soil \t moisture ").value == "soil moisture"

    def test_accepts_its_cap_and_refuses_one_character_more(self) -> None:
        tag = "x" * MAX_TAG_LENGTH
        assert Tag(tag).value == tag
        with pytest.raises(InvalidTagError, match="between 1 and 32 characters"):
            Tag(tag + "x")

    @pytest.mark.parametrize("text", ["", "   ", "\t"])
    def test_blank_is_refused(self, text: str) -> None:
        with pytest.raises(InvalidTagError):
            Tag(text)

    @pytest.mark.parametrize("text", ["esp32,i2c", "esp32\uff0ci2c"])  # the second is fullwidth
    def test_a_comma_is_refused_and_the_tag_named(self, text: str) -> None:
        with pytest.raises(InvalidTagError, match=re.escape(repr(text))):
            Tag(text)

    @pytest.mark.parametrize("text", ["esp\x0032", "bell\x07", "del\x7f"])
    def test_a_control_character_is_refused(self, text: str) -> None:
        with pytest.raises(InvalidTagError, match="control character"):
            Tag(text)


def _texts(count: int) -> list[str]:
    return [f"tag{number:02d}" for number in range(count)]


class TestTags:
    def test_holds_each_tag_once_in_alphabetical_order(self) -> None:
        assert Tags.of(["i2c", "ESP32", " esp32 ", "Outdoor"]).texts() == (
            "esp32",
            "i2c",
            "outdoor",
        )

    def test_twenty_one_distinct_tags_are_refused(self) -> None:
        with pytest.raises(TooManyTagsError, match="at most 20 tags"):
            Tags.of(_texts(MAX_TAGS + 1))

    def test_twenty_five_texts_holding_twenty_distinct_are_accepted(self) -> None:
        texts = _texts(MAX_TAGS) + [text.upper() for text in _texts(5)]
        assert len(texts) == 25
        assert Tags.of(texts).texts() == tuple(_texts(MAX_TAGS))

    def test_none_is_empty(self) -> None:
        assert Tags.none().texts() == ()
        assert Tags.none() == Tags.of([])

    def test_include_asks_for_every_wanted_tag(self) -> None:
        tags = Tags.of(["esp32", "i2c", "outdoor"])
        assert tags.include(Tags.of(["I2C", "esp32"]))
        assert tags.include(Tags.none())
        assert not tags.include(Tags.of(["esp32", "relay"]))

    def test_a_refused_text_names_itself(self) -> None:
        with pytest.raises(InvalidTagError, match="'a,b'"):
            Tags.of(["esp32", "a,b"])


class TestRevisionLabel:
    @pytest.mark.parametrize("text", ["A", "B", "v2", "1.1", "rev-c", "pcb_2", "x" * 16])
    def test_accepts_the_owners_schemes_and_keeps_them_as_typed(self, text: str) -> None:
        assert RevisionLabel(text).value == text

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "x" * 17,  # one past the cap
            "-a",  # a leading separator
            "a-",  # a trailing one
            ".1",
            "a_",
            "rev c",  # a space
            " A",
            "é",  # an accented letter: not ASCII
            "revé",
            "\uff21",  # fullwidth
            "a/b",
        ],
    )
    def test_refuses_anything_else(self, text: str) -> None:
        with pytest.raises(InvalidRevisionLabelError):
            RevisionLabel(text)

    def test_first_is_a(self) -> None:
        assert RevisionLabel.first() == RevisionLabel("A")

    def test_two_cases_of_one_label_fold_alike(self) -> None:
        assert RevisionLabel("Rev-C").fold() == RevisionLabel("rev-c").fold() == "rev-c"

    @pytest.mark.parametrize(
        ("label", "expected"),
        [
            ("A", "B"),
            ("Z", "AA"),
            ("AZ", "BA"),
            ("z", "aa"),
            ("Az", "BA"),  # mixed case steps as capitals
            ("v9", "v10"),
            ("v09", "v10"),
            ("1.9", "1.10"),
            ("rev-c", "rev-d"),
            ("099", "100"),
            ("a1b", "a1c"),
        ],
    )
    def test_successor_steps_the_trailing_run(self, label: str, expected: str) -> None:
        assert RevisionLabel(label).successor() == RevisionLabel(expected)

    @pytest.mark.parametrize("label", ["Z" * 16, "9" * 16, "v" + "9" * 15])
    def test_successor_is_none_past_sixteen_characters(self, label: str) -> None:
        assert RevisionLabel(label).successor() is None

    def test_successor_may_reach_the_cap_exactly(self) -> None:
        assert RevisionLabel("Z" * 15).successor() == RevisionLabel("A" * 16)


class TestRevisionStatus:
    def test_is_exactly_adr_0003s_four_states(self) -> None:
        assert [status.value for status in RevisionStatus] == [
            "draft",
            "reserved",
            "built",
            "dismantled",
        ]

    def test_refuses_a_fifth_state(self) -> None:
        with pytest.raises(ValueError, match="archived"):
            RevisionStatus("archived")


def test_every_value_error_is_a_projects_error() -> None:
    for error in (
        InvalidProjectNameError,
        InvalidTextError,
        InvalidSummaryError,
        InvalidTagError,
        TooManyTagsError,
        InvalidRevisionLabelError,
    ):
        assert issubclass(error, ProjectsError)


# --- Property 1: text values are fixpoints of their own rules ----------------------------

_LABEL_CHARACTERS = string.ascii_letters + string.digits + ".-_"
# Characters each rule treats specially: whitespace of every kind, the two line endings, a
# comma and its fullwidth form, controls, fullwidth letters, İ (which lower-cases to two
# characters) and accents.
_TRICKY = " \t\n\r\x0b\x1f\u00a0\u3000,\uff0c\x00\x07\x7f\uff21\uff5aİéÉAz09.-_"


def _texts_near(cap: int) -> st.SearchStrategy[str]:
    """Texts whose length straddles a cap, padded with whitespace to trim."""
    return st.builds(
        lambda pad, count, tail: f"{pad}{'x' * count}{tail}{pad}",
        st.sampled_from(["", " ", "\r\n", "\t "]),
        st.integers(min_value=cap - 2, max_value=cap + 1),
        st.sampled_from(["", "y", " y", "\ny"]),
    )


_ANY_TEXT = st.one_of(
    st.text(),
    st.text(alphabet=_TRICKY, max_size=12),
    st.text(alphabet=_LABEL_CHARACTERS + " é", max_size=18),
    _texts_near(MAX_TAG_LENGTH),
    _texts_near(MAX_PROJECT_NAME_LENGTH),
    _texts_near(MAX_TEXT_LENGTH),
)


def _accepted[V](kind: Callable[[str], V], text: str) -> V | None:
    try:
        return kind(text)
    except ProjectsError:
        return None


def _single_spaced(value: str) -> bool:
    """No run of whitespace, no whitespace other than a space, nothing at the ends."""
    return value.split(" ") == value.split()


def _check_collapsed[V: (ProjectName, Summary)](kind: type[V], cap: int, text: str) -> None:
    value = _accepted(kind, text)
    collapsed = " ".join(text.split())
    assert (value is None) == (not 1 <= len(collapsed) <= cap)
    if value is not None:
        assert kind(value.value) == value
        assert _single_spaced(value.value)


def _check_plain_text[V: (Description, Notes)](kind: type[V], text: str) -> None:
    value = _accepted(kind, text)
    unified = text.replace("\r\n", "\n").replace("\r", "\n")
    assert (value is None) == (not 1 <= len(unified.strip()) <= MAX_TEXT_LENGTH)
    if value is not None:
        assert kind(value.value) == value
        assert value.value in unified
        assert value.value.count("\n") == unified.strip().count("\n")
        assert "\r" not in value.value


def _check_tag(text: str) -> None:
    value = _accepted(Tag, text)
    normalized = " ".join(unicodedata.normalize("NFKC", text).lower().split())
    refused = (
        not 1 <= len(normalized) <= MAX_TAG_LENGTH
        or "," in normalized
        or any(unicodedata.category(char) == "Cc" for char in normalized)
    )
    assert (value is None) == refused
    if value is not None:
        assert Tag(value.value) == value
        assert _single_spaced(value.value)
        assert value.value == value.value.lower()


def _check_label(text: str) -> None:
    value = _accepted(RevisionLabel, text)
    alphanumeric = string.ascii_letters + string.digits
    refused = (
        not 1 <= len(text) <= MAX_LABEL_LENGTH
        or any(char not in _LABEL_CHARACTERS for char in text)
        or text[0] not in alphanumeric
        or text[-1] not in alphanumeric
    )
    assert (value is None) == refused
    if value is not None:
        assert RevisionLabel(value.value) == value
        assert value.value == text


@given(text=_ANY_TEXT)
def test_text_values_are_fixpoints_of_their_own_rules(text: str) -> None:
    """Property 1: text values are fixpoints of their own rules.

    For any text, each of ProjectName, Description, Notes, Summary, Tag and RevisionLabel
    either refuses it or accepts it as a value that, built again from its own stored text, is
    equal to it. An accepted description or notes keeps every inner line break of the text; a
    name, a summary or a tag has no run of whitespace left; a tag is lower-case; and the texts
    refused are exactly those that normalize to nothing or past the value's cap, a tag holding
    a comma or a control character, and a label holding a character outside its alphabet or
    starting or ending with '.', '-' or '_'.

    **Validates: Requirements 1.2, 1.4, 2.1, 2.2, 4.2, 4.7**
    """
    _check_collapsed(ProjectName, MAX_PROJECT_NAME_LENGTH, text)
    _check_collapsed(Summary, MAX_SUMMARY_LENGTH, text)
    _check_plain_text(Description, text)
    _check_plain_text(Notes, text)
    _check_tag(text)
    _check_label(text)


# --- Property 2: tags are a set ---------------------------------------------------------

# A small alphabet, so lists repeat tags in several spellings and pass twenty distinct often.
_TAG_TEXTS = st.text(alphabet="abcAB \uff42", min_size=1, max_size=3).filter(
    lambda text: _accepted(Tag, text) is not None
)


@given(texts=st.lists(_TAG_TEXTS, max_size=40), data=st.data())
def test_tags_are_a_set(texts: list[str], data: st.DataObject) -> None:
    """Property 2: tags are a set.

    For any list of texts Tag accepts, Tags.of gives the same tags whatever the order and the
    repetition of the list, holds them distinct and in alphabetical order, refuses exactly the
    lists holding more than 20 distinct tags, and gives the same tags back from
    Tags.of(tags.texts()).

    **Validates: Requirements 2.3, 2.4, 2.5**
    """
    distinct = {Tag(text).value for text in texts}
    if len(distinct) > MAX_TAGS:
        with pytest.raises(TooManyTagsError):
            Tags.of(texts)
        return
    tags = Tags.of(texts)
    shuffled = data.draw(st.permutations(texts))
    repeated = shuffled + data.draw(st.lists(st.sampled_from(texts))) if texts else shuffled
    assert Tags.of(repeated) == tags
    assert tags.texts() == tuple(sorted(distinct))
    assert Tags.of(tags.texts()) == tags


# --- Property 3: a label's successors never repeat -------------------------------------

_TRAILING_RUN = re.compile(r"(.*?)([0-9]+|[A-Za-z]+)")

_LABELS = st.one_of(
    st.from_regex(r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,14}[A-Za-z0-9])?", fullmatch=True),
    # Runs of Z and 9 near the cap, where the chain ends.
    st.builds(
        lambda prefix, run, count: prefix + run * count,
        st.sampled_from(["", "v", "rev-", "1.", "a"]),
        st.sampled_from(["Z", "z", "9", "zZ"]),
        st.integers(min_value=1, max_value=8),
    ).filter(lambda text: len(text) <= MAX_LABEL_LENGTH),
)


def _column(letters: str) -> int:
    """Spreadsheet-column number: A is 1, Z is 26, AA is 27."""
    number = 0
    for char in letters.upper():
        number = number * 26 + string.ascii_uppercase.index(char) + 1
    return number


def _column_width(number: int) -> int:
    width = 0
    while number:
        number = (number - 1) // 26
        width += 1
    return width


def _check_step(label: RevisionLabel, following: RevisionLabel | None) -> bool:
    """Checks one step of the chain; answers whether the chain goes on."""
    split = _TRAILING_RUN.fullmatch(label.value)
    assert split is not None
    prefix, run = split.groups()
    if run.isdigit():
        width = max(len(run), len(str(int(run) + 1)))
    else:
        width = _column_width(_column(run) + 1)
    if following is None:
        assert len(prefix) + width > MAX_LABEL_LENGTH
        return False
    assert following.value.startswith(prefix)
    stepped = following.value[len(prefix) :]
    assert len(stepped) == width
    if run.isdigit():
        assert int(stepped) == int(run) + 1
    else:
        assert _column(stepped) == _column(run) + 1
        assert stepped.islower() if run.islower() else stepped.isupper()
    return True


@given(start=_LABELS)
def test_a_labels_successors_never_repeat(start: str) -> None:
    """Property 3: a label's successors never repeat.

    For any valid label, following successor gives valid labels that are pairwise distinct
    when folded and keep everything before the trailing run; a trailing number goes up by
    exactly one at each step, trailing letters follow spreadsheet-column order, and the chain
    ends (None) only where the next label would pass 16 characters.

    **Validates: Requirements 4.2, 4.4, 4.6**
    """
    label = RevisionLabel(start)
    seen = {label.fold()}
    for _ in range(40):
        following = label.successor()
        if not _check_step(label, following):
            return
        assert following is not None
        assert RevisionLabel(following.value) == following
        assert following.fold() not in seen
        seen.add(following.fold())
        label = following
