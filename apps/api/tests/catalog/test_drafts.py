"""Part drafts over the in-memory catalog: reviewed and defined inside a caller's transaction.

The bench is *Passives → Resistors* with a required `resistance` in ohms, as every catalog
test's is. `PartDrafts` gets the fakes as bare repositories, the way inventory's intake will
hand it the shared session, so it can't open or commit anything: the tests hold it to that.
"""

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from uuid import uuid7

import pytest
from hypothesis import HealthCheck, given, settings

from support.catalog import (
    BENCH,
    InMemoryAttributeDefinitions,
    InMemoryCategories,
    World,
)
from support.pinouts import pinouts
from wiredex.catalog.application.drafts import DraftReview, PartDrafts, RawPartDraft
from wiredex.catalog.application.parts import NewPart
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import (
    DraftProblemKind,
    DraftRefusedError,
    DuplicateMpnError,
    PartNotFoundError,
)
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeValues
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
    SiValue,
)

pytestmark = pytest.mark.anyio

RESISTANCE = AttributeKey("resistance")
# A new resistor as a sheet row names it: its category by the tail of its path.
RESISTOR = RawPartDraft(
    category_path="Resistors", name="R 4k7 0805", attributes={"resistance": "4k7"}
)

type Found = list[tuple[str, DraftProblemKind]]


def drafts_of(world: World) -> PartDrafts:
    # The catalog fake passed as repositories alone, as bootstrap will pass the shared session.
    return PartDrafts(world.catalog, world.clock, world.ids)


def found(review: DraftReview) -> Found:
    return [(problem.field, problem.kind) for problem in review.problems]


def an_attribute(
    world: World,
    key: str,
    kind: AttributeKind,
    *,
    required: bool = False,
    options: tuple[str, ...] = (),
) -> AttributeDefinition:
    """An attribute on *Resistors*, written straight to the store as the World seeds."""
    definition = AttributeDefinition(
        AttributeDefinitionId(uuid7()),
        BENCH,
        world.resistors.id,
        AttributeKey(key),
        AttributeLabel(key),
        kind,
        None,
        required,
        options,
    )
    world.catalog.attribute_definitions.saved[definition.id] = definition
    return definition


def a_stored_resistor(world: World, manufacturer: str | None, mpn: str) -> PartDefinition:
    """A resistor already catalogued under a part number, written straight to the store."""
    part = PartDefinition.define(
        PartDefinitionId(uuid7()),
        world.resistors,
        PartDetails(
            PartName("R 4k7 1%"),
            None if manufacturer is None else Manufacturer(manufacturer),
            Mpn(mpn),
        ),
        AttributeValues({RESISTANCE: SiValue(Decimal(4700))}),
        world.clock.now(),
    )
    world.catalog.parts.saved[part.id] = part
    return part


def described(part: PartDefinition) -> tuple[object, ...]:
    """Everything a part holds but its id, which only the id generator decides."""
    return (
        part.workspace_id,
        part.category_id,
        part.details,
        dict(part.attributes),
        part.created_at,
        part.updated_at,
    )


async def test_a_new_part_is_reviewed_with_its_category_path_and_flag() -> None:
    world = World()

    review = await drafts_of(world).review(RESISTOR)

    assert review.problems == ()
    assert review.existing is None
    assert review.category is world.resistors
    assert review.category_path == "Passives / Resistors"
    assert review.tracked_individually is False
    # No part number, so nothing a later row could name it by (requirement 5.8).
    assert review.identity is None


async def test_every_problem_of_a_new_part_is_reported_at_once() -> None:
    # Requirements 1.5, 5.5 and 5.7: each field's problem, the form's order, one pass.
    world = World()
    an_attribute(world, "tolerance", AttributeKind.ENUM, required=True, options=("1%", "5%"))
    draft = RawPartDraft(
        category_path="passives/RESISTORS",
        name="   ",
        manufacturer="M" * 81,
        mpn="P" * 81,
        package="K" * 41,
        attributes={"tolerance": "2%", "resistence": "4k7", "Two words": "x"},
    )

    review = await drafts_of(world).review(draft)

    assert found(review) == [
        ("name", DraftProblemKind.MISSING),
        ("manufacturer", DraftProblemKind.INVALID),
        ("mpn", DraftProblemKind.INVALID),
        ("package", DraftProblemKind.INVALID),
        ("resistance", DraftProblemKind.MISSING),
        ("tolerance", DraftProblemKind.INVALID),
        ("resistence", DraftProblemKind.NOT_AN_ATTRIBUTE),
        ("Two words", DraftProblemKind.NOT_AN_ATTRIBUTE),
    ]
    messages = {problem.field: problem.message for problem in review.problems}
    assert messages["resistance"] == "resistance is required"
    assert "tolerance takes one of 1%, 5%" in messages["tolerance"]
    assert messages["manufacturer"] == "a manufacturer needs between 1 and 80 characters"
    # The category read fine, so the review still says where the part would go.
    assert review.category is world.resistors
    assert review.existing is None


def _no_category(_: World) -> RawPartDraft:
    return replace(RESISTOR, category_path=None)


def _an_unknown_id(_: World) -> RawPartDraft:
    return replace(RESISTOR, category_path=None, category_id=CategoryId(uuid7()))


def _an_unknown_path(_: World) -> RawPartDraft:
    return replace(RESISTOR, category_path="Passives / Capacitors")


def _an_ambiguous_path(world: World) -> RawPartDraft:
    world.add_category("Resistors", world.add_category("Legacy"))
    return RESISTOR


@pytest.mark.parametrize(
    ("draft_in", "kind"),
    [
        pytest.param(_no_category, DraftProblemKind.MISSING, id="no category"),
        pytest.param(_an_unknown_id, DraftProblemKind.UNKNOWN_CATEGORY, id="an unknown id"),
        pytest.param(_an_unknown_path, DraftProblemKind.UNKNOWN_CATEGORY, id="an unknown path"),
        pytest.param(_an_ambiguous_path, DraftProblemKind.AMBIGUOUS_CATEGORY, id="ambiguous"),
    ],
)
async def test_a_category_that_cant_be_read_is_the_problem_attributes_wait_for(
    draft_in: Callable[[World], RawPartDraft], kind: DraftProblemKind
) -> None:
    # Requirement 5.4: without a category there is no schema to check the values against.
    world = World()

    review = await drafts_of(world).review(draft_in(world))

    assert found(review) == [("category", kind)]
    assert (review.category, review.category_path, review.tracked_individually) == (
        None,
        None,
        None,
    )


async def test_an_ambiguous_path_names_every_path_it_could_be() -> None:
    world = World()

    review = await drafts_of(world).review(_an_ambiguous_path(world))

    assert "Legacy / Resistors or Passives / Resistors" in review.problems[0].message


async def test_a_stored_part_is_matched_by_its_folded_manufacturer_and_part_number() -> None:
    # Requirement 5.1: the row uses the stored part and ignores its other part cells, so a
    # row with no category and a junk attribute is not a problem when it names a part.
    world = World()
    stored = a_stored_resistor(world, "Yageo", "RC0805FR-074K7L")

    review = await drafts_of(world).review(
        RawPartDraft(manufacturer=" yageo ", mpn="rc0805fr-074k7l", attributes={"x y": "?"})
    )

    assert review.existing is stored
    assert review.problems == ()
    assert review.category is world.resistors
    assert review.category_path == "Passives / Resistors"
    assert review.tracked_individually is False


async def test_a_part_stored_without_a_manufacturer_is_named_only_without_one() -> None:
    # The unique index reads a missing manufacturer as empty text, and so does the review.
    world = World()
    stored = a_stored_resistor(world, None, "R-4K7")
    drafts = drafts_of(world)

    alone = await drafts.review(replace(RESISTOR, mpn="r-4k7"))
    with_a_maker = await drafts.review(replace(RESISTOR, manufacturer="Yageo", mpn="R-4K7"))

    assert alone.existing is stored
    assert with_a_maker.existing is None
    assert with_a_maker.problems == ()


async def test_the_flag_is_resolved_along_the_chain() -> None:
    # *Passives* is marked, *Resistors* inherits it, for a new part and a stored one alike.
    world = World()
    world.passives.tracked_individually = True
    a_stored_resistor(world, "Yageo", "RC0805")
    drafts = drafts_of(world)

    new = await drafts.review(RESISTOR)
    named = await drafts.review(RawPartDraft(manufacturer="Yageo", mpn="RC0805"))

    assert new.tracked_individually is True
    assert named.tracked_individually is True


async def test_the_not_stocked_flag_is_resolved_along_the_chain_apart_from_tracking() -> None:
    # 09's requirement 2.5: *Passives* is marked not stocked and *Resistors* tracked, and each
    # draft answers both, for a new part and a stored one alike.
    world = World()
    world.passives.not_stocked = True
    world.resistors.tracked_individually = True
    a_stored_resistor(world, "Yageo", "RC0805")
    drafts = drafts_of(world)

    new = await drafts.review(RESISTOR)
    named = await drafts.review(RawPartDraft(manufacturer="Yageo", mpn="RC0805"))

    assert (new.not_stocked, new.tracked_individually) == (True, True)
    assert (named.not_stocked, named.tracked_individually) == (True, True)


async def test_the_identity_is_the_manufacturer_and_part_number_folded() -> None:
    # What a sheet matches a later row on, the same whether or not the part is stored yet.
    world = World()
    drafts = drafts_of(world)

    typed = await drafts.review(replace(RESISTOR, manufacturer="Yageo", mpn="RC0805"))
    respelled = await drafts.review(replace(RESISTOR, manufacturer=" YAGEO ", mpn="rc0805"))
    no_maker = await drafts.review(replace(RESISTOR, mpn="RC0805"))
    blank = await drafts.review(replace(RESISTOR, manufacturer="Yageo", mpn="  "))
    a_stored_resistor(world, "Yageo", "RC0805")
    stored = await drafts.review(replace(RESISTOR, manufacturer="yageo", mpn="RC0805"))

    assert typed.identity is not None
    assert respelled.identity == typed.identity
    assert stored.identity == typed.identity
    assert no_maker.identity not in {None, typed.identity}
    assert blank.identity is None


@pytest.mark.parametrize(
    ("typed", "read"),
    [("yes", True), ("SIM", True), ("0", False), (" Não ", False)],
)
async def test_a_yes_or_no_attribute_is_read_from_text(typed: str, read: bool) -> None:
    # Requirement 5.9: a sheet can only hold text, in either language and any case.
    world = World()
    an_attribute(world, "lead_free", AttributeKind.BOOL)

    part = await drafts_of(world).define(
        replace(RESISTOR, attributes={"resistance": "4k7", "lead_free": typed})
    )

    assert part.attributes[AttributeKey("lead_free")] is read


async def test_other_text_for_a_yes_or_no_attribute_is_refused() -> None:
    world = World()
    an_attribute(world, "lead_free", AttributeKind.BOOL)

    review = await drafts_of(world).review(
        replace(RESISTOR, attributes={"resistance": "4k7", "lead_free": "maybe"})
    )

    assert found(review) == [("lead_free", DraftProblemKind.INVALID)]
    assert review.problems[0].message == "lead_free takes true or false, not 'maybe'"


async def test_a_defined_draft_is_the_part_define_part_would_have_stored() -> None:
    # One write path for a part, whichever door it came through (design, `define_part`).
    world = World()
    details = PartDetails(
        PartName("R 4k7 1%"), Manufacturer("Yageo"), Mpn("RC0805FR-074K7L"), Package("0805")
    )
    through_the_form = await world.define_part(
        BENCH, NewPart(world.resistors.id, details, {"resistance": "4k7"})
    )
    expected = described(through_the_form)
    # Out of the way again, so the draft's part number is free.
    del world.catalog.parts.saved[through_the_form.id]

    drafted = await drafts_of(world).define(
        RawPartDraft(
            category_id=world.resistors.id,
            name="R 4k7 1%",
            manufacturer="Yageo",
            mpn="RC0805FR-074K7L",
            package="0805",
            attributes={"resistance": "4k7"},
        )
    )

    assert described(drafted) == expected
    assert world.catalog.parts.saved == {drafted.id: drafted}


async def test_define_refuses_a_draft_with_problems_and_writes_nothing() -> None:
    world = World()
    draft = replace(RESISTOR, name=None, attributes={})
    drafts = drafts_of(world)

    with pytest.raises(DraftRefusedError) as refused:
        await drafts.define(draft)

    assert refused.value.problems == (await drafts.review(draft)).problems
    assert [problem.field for problem in refused.value.problems] == ["name", "resistance"]
    assert world.catalog.parts.saved == {}


async def test_define_refuses_a_draft_naming_a_stored_part() -> None:
    # Requirement 1.6: a stored part is named, never defined twice.
    world = World()
    stored = a_stored_resistor(world, "Yageo", "RC0805")

    with pytest.raises(DuplicateMpnError, match="already used by R 4k7 1%"):
        await drafts_of(world).define(replace(RESISTOR, manufacturer="YAGEO", mpn="rc0805"))

    assert world.catalog.parts.saved == {stored.id: stored}


async def test_a_duplicate_of_a_part_the_bench_doesnt_hold_writes_nothing() -> None:
    # Requirement 3.4: the source is looked for before the part is written.
    world = World()

    with pytest.raises(PartNotFoundError):
        await drafts_of(world).define(RESISTOR, pinout_from=PartDefinitionId(uuid7()))

    assert world.catalog.parts.saved == {}
    assert world.catalog.pinouts.saved == {}


async def test_drafts_never_open_or_commit_a_transaction() -> None:
    # The caller's unit of work owns the transaction (design decision 2).
    world = World()
    source = world.add_part(world.resistors, "BME280")
    drafts = drafts_of(world)

    await drafts.review(RESISTOR)
    await drafts.define(RESISTOR)
    await drafts.define(replace(RESISTOR, name="R 4k7 copy"), pinout_from=source.id)

    assert len(world.catalog.parts.saved) == 3
    assert world.catalog.commits == 0
    assert world.catalog.opened_for == []


class CountedCategories(InMemoryCategories):
    """The seeded tree, counting how often it is read whole, by id, and by chain."""

    def __init__(self, seeded: InMemoryCategories) -> None:
        super().__init__()
        self.saved = seeded.saved
        self.wholes = 0
        self.gets = 0
        self.chains: Counter[CategoryId] = Counter()

    async def all(self) -> list[Category]:
        self.wholes += 1
        return await super().all()

    async def get(self, category_id: CategoryId) -> Category | None:
        self.gets += 1
        return await super().get(category_id)

    async def ancestors(self, category_id: CategoryId) -> list[Category]:
        self.chains[category_id] += 1
        return await super().ancestors(category_id)


class CountedDefinitions(InMemoryAttributeDefinitions):
    """The seeded definitions, counting each chain whose definitions are read."""

    def __init__(self, seeded: InMemoryAttributeDefinitions) -> None:
        super().__init__()
        self.saved = seeded.saved
        self.reads: Counter[tuple[CategoryId, ...]] = Counter()

    async def of_categories(self, category_ids: Sequence[CategoryId]) -> list[AttributeDefinition]:
        self.reads[tuple(category_ids)] += 1
        return await super().of_categories(category_ids)


async def test_a_batch_reads_the_tree_once_and_each_schema_once() -> None:
    # Requirement 12.2: a sheet of five hundred rows costs what a sheet of six does.
    world = World()
    capacitors = world.add_category("Capacitors")
    categories = CountedCategories(world.catalog.categories)
    definitions = CountedDefinitions(world.catalog.attribute_definitions)
    world.catalog.categories = categories
    world.catalog.attribute_definitions = definitions
    drafts = drafts_of(world)
    batch = [
        RESISTOR,
        replace(RESISTOR, name="R 10k 0805", attributes={"resistance": "10k"}),
        replace(RESISTOR, category_path=None, category_id=world.resistors.id),
        RawPartDraft(category_path="Capacitors", name="C 100n 0603"),
        RawPartDraft(category_id=capacitors.id, name="C 1u 0805"),
        RawPartDraft(category_path="Nowhere", name="Lost"),
    ]

    for draft in batch:
        await drafts.review(draft)

    assert categories.wholes == 1
    # A category picked by id is found in the tree already read, not asked for again.
    assert categories.gets == 0
    assert categories.chains == Counter({world.resistors.id: 1, capacitors.id: 1})
    assert definitions.reads == Counter(
        {(world.passives.id, world.resistors.id): 1, (capacitors.id,): 1}
    )
    # Another instance is another transaction, so it reads the tree afresh.
    await drafts_of(world).review(RESISTOR)
    assert categories.wholes == 2


# --- Property 8: a duplicate carries its source's pinout ---------------------------------


# The only function-scoped fixture in reach is `anyio_backend`, which names the event loop
# and carries no state; each example builds its own World, so nothing crosses between them.
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pinout=pinouts())
async def test_a_duplicate_carries_its_source_pinout(pinout: Pinout) -> None:
    """Property 8: a duplicate carries its source's pinout.

    Defining a duplicate with `pinout_from` gives the new part a pinout equal to the
    source's, pin for pin and in order, and leaves the source and its pinout unchanged.

    **Validates: Requirements 3.2, 3.3**
    """
    world = World()
    source = a_stored_resistor(world, "Bosch", "BME280")
    world.catalog.pinouts.saved[source.id] = pinout
    before = described(source)
    world.clock.advance(timedelta(hours=1))

    duplicate = await drafts_of(world).define(
        replace(RESISTOR, name="BME280 copy", manufacturer="Bosch"), pinout_from=source.id
    )

    copied = await world.catalog.pinouts.of_part(duplicate.id)
    assert duplicate.id != source.id
    assert copied == pinout
    assert list(copied) == list(pinout)
    assert await world.catalog.pinouts.of_part(source.id) == pinout
    assert described(source) == before
    assert world.catalog.commits == 0
