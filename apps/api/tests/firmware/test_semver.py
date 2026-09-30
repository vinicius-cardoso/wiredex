import json
import operator
from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.firmware.domain.errors import InvalidVersionError
from wiredex.firmware.domain.semver import (
    FIRST_VERSION,
    MAX_VERSION_LENGTH,
    Identifier,
    SemVer,
    suggested_version,
)

# SemVer 2.0.0 §11's own example of pre-release precedence, lowest first.
SPECIFICATION_CHAIN = (
    "1.0.0-alpha",
    "1.0.0-alpha.1",
    "1.0.0-alpha.beta",
    "1.0.0-beta",
    "1.0.0-beta.2",
    "1.0.0-beta.11",
    "1.0.0-rc.1",
    "1.0.0",
)
AT_THE_CAP = "1.0.0-" + "a" * (MAX_VERSION_LENGTH - len("1.0.0-"))


class TestParse:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("1.2.0", SemVer(1, 2, 0)),
            ("0.0.0", SemVer(0, 0, 0)),
            ("10.20.30", SemVer(10, 20, 30)),
            ("v1.2.0", SemVer(1, 2, 0)),
            (" \t1.2.0\n", SemVer(1, 2, 0)),
            ("  v1.2.0\u3000", SemVer(1, 2, 0)),
            ("1.3.0-rc.1", SemVer(1, 3, 0, ("rc", 1))),
            ("1.0.0-alpha.beta", SemVer(1, 0, 0, ("alpha", "beta"))),
            ("1.0.0-0", SemVer(1, 0, 0, (0,))),
            ("1.0.0-0a.01b", SemVer(1, 0, 0, ("0a", "01b"))),  # words may start with a zero
            ("1.0.0-x-y-z.--", SemVer(1, 0, 0, ("x-y-z", "--"))),
        ],
    )
    def test_reads_requirement_5_1s_grammar(self, text: str, expected: SemVer) -> None:
        assert SemVer.parse(text) == expected

    @pytest.mark.parametrize("text", ["1.0.0-RC.1", "1.0.0-Rc.1", "v1.0.0-rC.1"])
    def test_keeps_the_number_lower_cased(self, text: str) -> None:
        assert SemVer.parse(text) == SemVer.parse("1.0.0-rc.1")
        assert str(SemVer.parse(text)) == "1.0.0-rc.1"

    @pytest.mark.parametrize("text", ["01.2.0", "1.02.0", "1.2.00", "v1.2.0-rc.01", "1.2.0-00.a"])
    def test_refuses_a_number_with_a_leading_zero(self, text: str) -> None:
        with pytest.raises(InvalidVersionError, match="leading zero") as refused:
            SemVer.parse(text)
        assert refused.value.item == text

    @pytest.mark.parametrize(
        "text", ["1.2.0+build.5", "1.2.0-rc.1+esp32", " v1.2.0+20260930 ", "1.2.0+"]
    )
    def test_refuses_build_metadata_rather_than_dropping_it(self, text: str) -> None:
        with pytest.raises(InvalidVersionError, match="build metadata") as refused:
            SemVer.parse(text)
        assert refused.value.item == text

    def test_accepts_64_characters_and_refuses_65(self) -> None:
        assert len(AT_THE_CAP) == MAX_VERSION_LENGTH
        assert str(SemVer.parse(AT_THE_CAP)) == AT_THE_CAP
        with pytest.raises(InvalidVersionError, match="at most 64 characters") as refused:
            SemVer.parse(AT_THE_CAP + "b")
        assert refused.value.item == AT_THE_CAP + "b"

    def test_the_cap_counts_the_number_not_its_v_or_the_whitespace_around_it(self) -> None:
        assert SemVer.parse(f"  v{AT_THE_CAP}\n") == SemVer.parse(AT_THE_CAP)

    def test_thousands_of_digits_are_refused_not_crashed_on(self) -> None:
        # int() refuses more than 4,300 digits with an error of its own.
        with pytest.raises(InvalidVersionError, match="at most 64 characters"):
            SemVer.parse("1" * 5_000 + ".0.0")

    @pytest.mark.parametrize(
        "text",
        [
            "",
            "   ",
            "v",
            "1",
            "1.2",
            "1.2.3.4",
            "1.x.0",
            "one.two.three",
            "-1.2.0",
            "vv1.2.0",
            "V1.2.0",  # requirement 5.1's `v` is lower-case, as tags write it
            "v 1.2.0",
            "1.2.0-",
            "1.2.0-rc..1",
            "1.2.0-rc.",
            "1.2.0-rc_1",
            "1.2.0 rc.1",
            "1.2.0-é",  # an accented letter: not ASCII
            "1.2.0-\u212a",  # the Kelvin sign, which lower() would turn into an ASCII k
            "\uff11.\uff12.\uff13",  # fullwidth digits
            "\u0661.\u0662.\u0663",  # Arabic-Indic digits, which int() reads
        ],
    )
    def test_refuses_anything_else_naming_it(self, text: str) -> None:
        with pytest.raises(InvalidVersionError, match="is not a version number like") as refused:
            SemVer.parse(text)
        assert refused.value.item == text

    def test_names_half_of_a_surrogate_pair_by_its_escape(self) -> None:
        # What json.loads makes of "1.2.0-\ud800": the grammar refuses it, and the refusal can't
        # name it as typed, since the answer carrying it is UTF-8, which can't encode it.
        with pytest.raises(InvalidVersionError, match="is not a version number like") as refused:
            SemVer.parse(json.loads('"1.2.0-\\ud800"'))
        assert refused.value.item == "1.2.0-\\ud800"
        assert str(refused.value).startswith("'1.2.0-\\ud800' is not")


class TestSemVer:
    @pytest.mark.parametrize(
        ("number", "text"),
        [
            (SemVer(1, 2, 0), "1.2.0"),
            (SemVer(1, 3, 0, ("rc", 1)), "1.3.0-rc.1"),
            (SemVer(0, 0, 1, ("x-y", 0, "0a")), "0.0.1-x-y.0.0a"),
        ],
    )
    def test_writes_its_canonical_text(self, number: SemVer, text: str) -> None:
        assert str(number) == text

    @pytest.mark.parametrize(
        ("major", "minor", "patch", "prerelease"),
        [
            (-1, 0, 0, ()),
            (1, -2, 0, ()),
            (True, 0, 0, ()),  # a bool is an int to Python, not a number here
            (1, 0, 0, ("RC",)),
            (1, 0, 0, ("1",)),  # digits alone are a number, stored as one
            (1, 0, 0, ("",)),
            (1, 0, 0, ("a.b",)),
            (1, 0, 0, (-1,)),
            (1, 0, 0, (False,)),
        ],
    )
    def test_is_refused_built_from_parts_parse_would_not_read(
        self, major: int, minor: int, patch: int, prerelease: tuple[Identifier, ...]
    ) -> None:
        with pytest.raises(InvalidVersionError, match="is not a version number"):
            SemVer(major, minor, patch, prerelease)

    @pytest.mark.parametrize(
        ("lower", "higher"),
        [
            ("1.0.0", "2.0.0"),
            ("2.0.0", "2.1.0"),
            ("2.1.0", "2.1.1"),
            ("1.9.0", "1.10.0"),  # numbers compare as numbers, not as text
            ("1.0.0-rc.2", "1.0.0-rc.10"),
            ("1.0.0-rc.1", "1.0.0-rc.a"),  # a number before a word
            ("1.0.0-2.a", "1.0.0-10"),  # the first difference decides, not the length
            ("0.9.9", "1.0.0-alpha"),  # a pre-release is still above a lower core
        ],
    )
    def test_orders_by_precedence(self, lower: str, higher: str) -> None:
        assert SemVer.parse(lower) < SemVer.parse(higher)
        assert SemVer.parse(higher) > SemVer.parse(lower)
        assert not SemVer.parse(higher) < SemVer.parse(lower)

    def test_compares_only_with_another_version_number(self) -> None:
        with pytest.raises(TypeError):
            operator.lt(SemVer(1, 0, 0), "1.0.0")


class TestSuccessor:
    @pytest.mark.parametrize(
        ("number", "expected"),
        [
            ("1.2.0", "1.2.1"),
            ("0.1.0", "0.1.1"),
            ("1.2.9", "1.2.10"),
            ("1.3.0-rc.1", "1.3.0-rc.2"),
            ("1.3.0-rc.9", "1.3.0-rc.10"),
            ("1.0.0-0", "1.0.0-1"),
            ("1.3.0-beta", "1.3.0-beta.1"),
            ("1.0.0-alpha.beta", "1.0.0-alpha.beta.1"),
            ("1.0.0-1.a", "1.0.0-1.a.1"),
        ],
    )
    def test_steps_as_requirement_5_4_reads(self, number: str, expected: str) -> None:
        successor = SemVer.parse(number).successor()
        assert str(successor) == expected
        assert SemVer.parse(number) < successor


class TestSuggestedVersion:
    def test_a_firmware_with_no_version_starts_at_0_1_0(self) -> None:
        assert suggested_version([]) == FIRST_VERSION == SemVer.parse("0.1.0")

    def test_steps_the_highest_whatever_the_order(self) -> None:
        # The weather station's versions: 1.2.0 is a draft, and the highest all the same.
        existing = [SemVer.parse(text) for text in ("1.1.0", "1.2.0", "1.0.0")]
        assert str(suggested_version(existing)) == "1.2.1"

    def test_a_pre_release_above_every_release_is_the_one_stepped(self) -> None:
        existing = [SemVer.parse(text) for text in ("1.1.0", "1.2.0-rc.1")]
        assert str(suggested_version(existing)) == "1.2.0-rc.2"

    def test_a_release_is_stepped_rather_than_its_pre_releases(self) -> None:
        existing = [SemVer.parse(text) for text in ("2.0.0-rc.1", "2.0.0", "2.0.0-beta")]
        assert str(suggested_version(existing)) == "2.0.1"


# --- Strategies ------------------------------------------------------------------------------

# Small pools, so two numbers often share a core and the start of a pre-release: independent
# draws would almost never tie, and the rules past the first difference would go untested.
# 2 and 10 are there because their text order isn't their order; the words are one of each
# shape the grammar allows: letters, digits then a letter, hyphens.
_POOLED_PARTS = st.sampled_from([0, 1, 2, 10])
_POOLED_IDENTIFIERS: st.SearchStrategy[Identifier] = _POOLED_PARTS | st.sampled_from(
    ["alpha", "rc", "a", "0a", "-", "x-y"]
)
# Numbers of one, a few and many digits, whose text order is often not their order.
_ANY_NUMERIC = st.integers(0, 9) | st.integers(10, 999) | st.integers(1_000, 10**12)
# Any identifier the grammar reads: numbers of any size, and words of every shape it allows.
_ANY_IDENTIFIERS = _ANY_NUMERIC | st.from_regex(r"[0-9]{0,3}[a-z-][0-9a-z-]{0,8}", fullmatch=True)


def _built_from(
    parts: st.SearchStrategy[int], identifiers: st.SearchStrategy[Identifier]
) -> st.SearchStrategy[SemVer]:
    prereleases = st.lists(identifiers, max_size=4).map(tuple)
    return st.builds(SemVer, parts, parts, parts, prereleases)


version_numbers = _built_from(_POOLED_PARTS, _POOLED_IDENTIFIERS) | _built_from(
    _ANY_NUMERIC, _ANY_IDENTIFIERS
)


@st.composite
def _neighbours(draw: st.DrawFn, number: SemVer) -> SemVer:
    """A number with this one's core and the start of its pre-release, itself included: two
    numbers that differ only where §11's later rules decide."""
    kept = number.prerelease[: draw(st.integers(0, len(number.prerelease)))]
    tail = draw(st.lists(_POOLED_IDENTIFIERS, max_size=2))
    return SemVer(number.major, number.minor, number.patch, (*kept, *tail))


@st.composite
def _renumbered(draw: st.DrawFn, number: SemVer) -> SemVer:
    """This number with other numbers where its pre-release has numbers, so that the first
    difference, when there is one, is between two numbers (§11.4.1)."""
    prerelease = tuple(
        draw(_ANY_NUMERIC) if isinstance(part, int) else part for part in number.prerelease
    )
    return SemVer(number.major, number.minor, number.patch, prerelease)


def _near(number: SemVer) -> st.SearchStrategy[SemVer]:
    return _neighbours(number) | _renumbered(number) | version_numbers


@st.composite
def _spellings(draw: st.DrawFn, number: SemVer) -> str:
    """The number as the owner might type it: letters in any case, with a leading v or not,
    and whitespace around it."""
    cased = "".join(draw(st.sampled_from([char, char.upper()])) for char in str(number))
    prefix = draw(st.sampled_from(["", "v"]))
    padding = draw(st.sampled_from(["", " ", "\t", "\n ", "\u3000"]))
    return f"{padding}{prefix}{cased}{padding}"


# --- Property 1: a version number reads back as itself -------------------------------------

# Characters the grammar treats specially, and look-alikes it must not take: other scripts'
# digits, the Kelvin sign, a no-break space.
_TRICKY = "0123456789.-+vVrcRC \t\u00a0\u0661\uff11\u212a"


def _accepted(text: str) -> SemVer | None:
    try:
        return SemVer.parse(text)
    except InvalidVersionError:
        return None


def _check_canonical(number: SemVer) -> None:
    canonical = str(number)
    assert SemVer.parse(canonical) == number
    assert str(SemVer.parse(canonical)) == canonical
    assert canonical == canonical.lower()
    assert not canonical.startswith("v")


@given(
    text=st.text() | st.text(alphabet=_TRICKY, max_size=16),
    number=version_numbers.filter(lambda number: len(str(number)) <= MAX_VERSION_LENGTH),
    data=st.data(),
)
def test_a_version_number_reads_back_as_itself(
    text: str, number: SemVer, data: st.DataObject
) -> None:
    """Property 1: a version number reads back as itself.

    For any text SemVer.parse accepts, str(SemVer.parse(text)) is canonical: parsing it again
    gives an equal number, it is lower-case, and it has no leading v. The texts are drawn at
    random and as spellings of a number, in any case, with a leading v or not and whitespace
    around it, which parse as that number.

    **Validates: Requirements 5.1**
    """
    accepted = _accepted(text)
    if accepted is not None:
        _check_canonical(accepted)
    parsed = SemVer.parse(data.draw(_spellings(number)))
    assert parsed == number
    _check_canonical(parsed)


# --- Property 2: versions order by SemVer 2.0.0 precedence ---------------------------------


def _reference(first: str, second: str) -> int:
    """SemVer 2.0.0 §11 read off two canonical texts, step by step: below 0 when the first has
    the lower precedence, 0 when the two have the same, above 0 otherwise."""
    first_core, _, first_prerelease = first.partition("-")
    second_core, _, second_prerelease = second.partition("-")
    # §11.2: major, minor and patch, compared numerically, left to right.
    core = _compare_identifier_lists(first_core.split("."), second_core.split("."))
    if core:
        return core
    # §11.3: with equal cores, a pre-release has lower precedence than the release.
    if not (first_prerelease and second_prerelease):
        return bool(second_prerelease) - bool(first_prerelease)
    # §11.4: identifiers left to right, and a longer list above a shorter one it starts with.
    return _compare_identifier_lists(first_prerelease.split("."), second_prerelease.split("."))


def _compare_identifier_lists(first: list[str], second: list[str]) -> int:
    for mine, theirs in zip(first, second, strict=False):
        order = _compare_identifiers(mine, theirs)
        if order:
            return order
    return len(first) - len(second)


def _compare_identifiers(mine: str, theirs: str) -> int:
    """§11.4.1 to §11.4.3: digits alone compare numerically and below anything else; the rest
    compare lexically, in ASCII order."""
    if mine.isdigit() and theirs.isdigit():
        return int(mine) - int(theirs)
    if mine.isdigit() != theirs.isdigit():
        return -1 if mine.isdigit() else 1
    return (mine > theirs) - (mine < theirs)


@given(first=version_numbers, data=st.data())
def test_versions_order_by_semver_precedence(first: SemVer, data: st.DataObject) -> None:
    """Property 2: versions order by SemVer 2.0.0 precedence.

    For any two numbers, a < b agrees with a reference comparison the test writes from SemVer
    §11, and the order is total: exactly one of a < b, b < a and a == b holds, a == b only for
    one canonical text, and it is transitive. Each number is drawn near the one before, often
    equal to it or sharing its core, so ties and the pre-release rules are met as often as the
    core's. The specification's own chain is the next test.

    **Validates: Requirements 5.3**
    """
    second = data.draw(_near(first))
    third = data.draw(_near(second))
    for a, b in ((first, second), (second, third), (first, third)):
        expected = _reference(str(a), str(b))
        assert (a < b) == (expected < 0)
        assert (b < a) == (expected > 0)
        assert (a == b) == (expected == 0)
        assert (a == b) == (str(a) == str(b))
    if first < second < third:
        assert first < third


@given(order=st.permutations(SPECIFICATION_CHAIN))
def test_semvers_own_precedence_chain_holds(order: list[str]) -> None:
    """Property 2, its last clause: the specification's own chain holds, 1.0.0-alpha <
    1.0.0-alpha.1 < 1.0.0-alpha.beta < 1.0.0-beta < 1.0.0-beta.2 < 1.0.0-beta.11 < 1.0.0-rc.1
    < 1.0.0, the reference comparison agrees with it, and sorting the numbers in any order
    gives it back.

    **Validates: Requirements 5.3**
    """
    chain = [SemVer.parse(text) for text in SPECIFICATION_CHAIN]
    for lower, higher in pairwise(chain):
        assert lower < higher
        assert _reference(str(lower), str(higher)) < 0
    assert sorted(SemVer.parse(text) for text in order) == chain


# --- Property 3: the suggested version is free and above every version ----------------------


@given(existing=st.frozensets(version_numbers, max_size=8))
def test_the_suggested_version_is_free_and_above_every_version(
    existing: frozenset[SemVer],
) -> None:
    """Property 3: the suggested version is free and above every version.

    For any set of numbers, suggested_version is above every one of them and equal to none;
    for the empty set it is 0.1.0.

    **Validates: Requirements 5.4**
    """
    suggested = suggested_version(existing)
    assert all(number < suggested for number in existing)
    assert suggested not in existing
    if not existing:
        assert suggested == SemVer(0, 1, 0)
