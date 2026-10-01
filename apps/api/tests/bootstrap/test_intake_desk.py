"""`CatalogPartDesk` over the in-memory catalog: catalog's part drafts in inventory's words.

The desk is where catalog's answers and refusals become inventory's (design, Error Handling),
so the tests drive a real `PartDrafts` over the catalog fakes, as the shared session drives it
over the SQL repositories. The bench is *Passives → Resistors*, with a required `resistance`
in ohms, as every catalog test's is.
"""

from dataclasses import dataclass, replace
from uuid import uuid7

import pytest

from support.catalog import World
from wiredex.bootstrap.intake import CatalogPartDesk
from wiredex.catalog.application.drafts import PartDrafts
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import DraftProblemKind
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout, RawPin
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    Manufacturer,
    Mpn,
    PartDefinitionId,
    PartName,
)
from wiredex.inventory.application.ports import PartReview
from wiredex.inventory.domain.errors import (
    IntakeRefusedError,
    PartAlreadyDefinedError,
    PartNotFoundError,
)
from wiredex.inventory.domain.intake import CellProblem, KnownPart, PartDraft, ProblemCode
from wiredex.inventory.domain.values import PartId

pytestmark = pytest.mark.anyio

# A new resistor as a sheet row names it: its category by its path.
RESISTOR = PartDraft(
    category_path="Passives / Resistors", name="R 4k7 0805", attributes={"resistance": "4k7"}
)

type Found = list[tuple[int | None, str | None, ProblemCode]]


def desk_of(world: World) -> CatalogPartDesk:
    # The catalog fake as bare repositories, as the intake unit of work hands it the session.
    return CatalogPartDesk(PartDrafts(world.catalog, world.clock, world.ids))


def found(problems: tuple[CellProblem, ...]) -> Found:
    return [(problem.row, problem.column, problem.code) for problem in problems]


def a_board_category(world: World) -> Category:
    """A root *Boards* whose parts are tracked as individual units."""
    boards = world.add_category("Boards")
    boards.tracked_individually = True
    return boards


def a_stored_part(
    world: World, category: Category, name: str, manufacturer: str, mpn: str
) -> PartDefinition:
    """A part already catalogued under a part number, written straight to the store."""
    part = PartDefinition.define(
        PartDefinitionId(uuid7()),
        category,
        PartDetails(PartName(name), Manufacturer(manufacturer), Mpn(mpn)),
        AttributeValues(),
        world.clock.now(),
    )
    world.catalog.parts.saved[part.id] = part
    return part


@dataclass(frozen=True, slots=True)
class KindCase:
    """A draft with exactly one problem, of `kind`, on `column`."""

    draft: PartDraft
    column: str
    kind: DraftProblemKind


# The world adds *Legacy / Resistors* beside *Passives / Resistors*, so the bare name is
# ambiguous.
KIND_CASES = (
    KindCase(
        replace(RESISTOR, category_path="Capacitors"),
        "category",
        DraftProblemKind.UNKNOWN_CATEGORY,
    ),
    KindCase(
        replace(RESISTOR, category_path="Resistors"),
        "category",
        DraftProblemKind.AMBIGUOUS_CATEGORY,
    ),
    KindCase(replace(RESISTOR, name=None), "name", DraftProblemKind.MISSING),
    KindCase(replace(RESISTOR, manufacturer="M" * 81), "manufacturer", DraftProblemKind.INVALID),
    KindCase(
        replace(RESISTOR, attributes={"resistance": "4k7", "resistence": "1k"}),
        "resistence",
        DraftProblemKind.NOT_AN_ATTRIBUTE,
    ),
    # The world below keeps a part with this MPN in the trash (16-soft-delete-and-trash).
    KindCase(
        replace(RESISTOR, manufacturer="Yageo", mpn="RC-IN-THE-TRASH"),
        "mpn",
        DraftProblemKind.PART_IN_TRASH,
    ),
)


def test_every_draft_problem_kind_has_the_problem_code_of_its_name() -> None:
    # Spelled the same too, so the web translates one code whichever module found it.
    kinds = {kind.name: kind.value for kind in DraftProblemKind}
    codes = {code.name: code.value for code in ProblemCode}
    assert kinds.items() <= codes.items()
    # And the table below drives every kind through the desk.
    assert {case.kind for case in KIND_CASES} == set(DraftProblemKind)


@pytest.mark.parametrize("case", KIND_CASES, ids=lambda case: str(case.kind))
async def test_each_draft_problem_reaches_inventory_on_its_column(case: KindCase) -> None:
    world = World()
    world.add_category("Resistors", world.add_category("Legacy"))
    trashed = a_stored_part(world, world.resistors, "R 4k7", "Yageo", "RC-IN-THE-TRASH")
    trashed.move_to_trash(world.clock.now())

    review = await desk_of(world).review(case.draft)

    # No row: the planner stamps it, and a quick-add has none.
    assert found(review.problems) == [(None, case.column, ProblemCode[case.kind.name])]
    assert review.existing is None


async def test_a_new_part_is_reviewed_with_its_category_path_and_flag() -> None:
    world = World()

    review = await desk_of(world).review(RESISTOR)

    assert review == PartReview(
        problems=(),
        existing=None,
        category_id=world.resistors.id,
        category_path="Passives / Resistors",
        tracked_individually=False,
        identity=None,
        not_stocked=False,
    )


async def test_a_stored_part_is_named_with_the_flag_of_its_category() -> None:
    world = World()
    board = a_stored_part(
        world, a_board_category(world), "ESP32-DevKitC", "Espressif", "ESP32-DEVKITC-32E"
    )

    # Matched folded, and not judged on the cells it doesn't use: no category, no name.
    review = await desk_of(world).review(
        PartDraft(manufacturer="espressif", mpn="esp32-devkitc-32e")
    )

    assert review.problems == ()
    assert review.existing == KnownPart(PartId(board.id), "ESP32-DevKitC", True, False)
    assert review.category_path == "Boards"
    assert review.tracked_individually is True
    assert review.identity is not None


async def test_the_not_stocked_flag_is_carried_for_a_new_part_a_stored_one_and_a_definition() -> (
    None
):
    # 09's requirement 2.5: the planner learns it for every kind of row. Passives sets it, so
    # Resistors inherits it, and it resolves apart from the tracking flag.
    world = World()
    world.passives.not_stocked = True
    stored = a_stored_part(world, world.resistors, "R 4k7 1%", "Yageo", "RC0805FR-074K7L")
    desk = desk_of(world)

    new = await desk.review(RESISTOR)
    named = await desk.review(PartDraft(manufacturer="yageo", mpn="rc0805fr-074k7l"))
    defined = await desk.define(RESISTOR)

    assert (new.not_stocked, new.tracked_individually) == (True, False)
    assert named.existing == KnownPart(PartId(stored.id), "R 4k7 1%", False, True)
    assert (defined.tracked_individually, defined.not_stocked) == (False, True)


async def test_a_draft_whose_category_is_unknown_has_no_not_stocked_answer() -> None:
    world = World()

    review = await desk_of(world).review(replace(RESISTOR, category_path="Nowhere"))

    assert (review.not_stocked, review.tracked_individually) == (None, None)


async def test_define_answers_the_part_with_how_it_is_counted_and_commits_nothing() -> None:
    world = World()
    boards = a_board_category(world)
    desk = desk_of(world)

    # A quick-add picks its category by id; a sheet names it by path.
    board = await desk.define(PartDraft(category_id=boards.id, name="  ESP32  "))
    resistor = await desk.define(RESISTOR)

    assert board == KnownPart(board.id, "ESP32", tracked_individually=True, not_stocked=False)
    assert resistor == KnownPart(
        resistor.id, "R 4k7 0805", tracked_individually=False, not_stocked=False
    )
    stored = world.catalog.parts.saved
    assert stored[PartDefinitionId(board.id)].category_id == boards.id
    assert stored[PartDefinitionId(resistor.id)].category_id == world.resistors.id
    # The caller's unit of work commits, never the desk.
    assert world.catalog.commits == 0


async def test_define_copies_the_pinout_of_a_duplicates_source() -> None:
    world = World()
    source = world.add_part(world.resistors)
    pinout = Pinout.parse(
        [RawPin(number="1", label="A", type="io"), RawPin(number="2", label="B", type="io")]
    )
    world.catalog.pinouts.saved[source.id] = pinout

    copy = await desk_of(world).define(RESISTOR, pinout_from=PartId(source.id))

    assert await world.catalog.pinouts.of_part(PartDefinitionId(copy.id)) == pinout


async def test_a_refused_draft_is_refused_with_inventorys_problems() -> None:
    world = World()

    with pytest.raises(IntakeRefusedError) as refused:
        await desk_of(world).define(replace(RESISTOR, name=None, attributes={}))

    assert found(refused.value.problems) == [
        (None, "name", ProblemCode.MISSING),
        (None, "resistance", ProblemCode.MISSING),
    ]
    assert world.catalog.parts.saved == {}


async def test_a_taken_part_number_is_refused_naming_its_holder() -> None:
    world = World()
    holder = a_stored_part(world, world.resistors, "R 4k7 1%", "Yageo", "RC0805FR-074K7L")
    draft = replace(RESISTOR, manufacturer="YAGEO", mpn="rc0805fr-074k7l")

    with pytest.raises(PartAlreadyDefinedError, match="RC0805FR-074K7L is already") as refused:
        await desk_of(world).define(draft)

    assert refused.value.part == KnownPart(PartId(holder.id), "R 4k7 1%", False, False)
    assert list(world.catalog.parts.saved) == [holder.id]


async def test_a_missing_pinout_source_is_inventorys_part_not_found() -> None:
    world = World()

    with pytest.raises(PartNotFoundError):
        await desk_of(world).define(RESISTOR, pinout_from=PartId(uuid7()))

    assert world.catalog.parts.saved == {}


async def test_a_category_gone_since_the_review_is_an_unknown_category() -> None:
    # The desk's `PartDrafts` reads the tree once; the write reads the category again, and
    # another request deleted it in between.
    world = World()
    desk = desk_of(world)
    await desk.review(RESISTOR)
    del world.catalog.categories.saved[world.resistors.id]

    with pytest.raises(IntakeRefusedError) as refused:
        await desk.define(RESISTOR)

    assert found(refused.value.problems) == [(None, "category", ProblemCode.UNKNOWN_CATEGORY)]
    assert world.catalog.parts.saved == {}


async def test_a_value_refused_since_the_review_is_a_problem_of_the_part() -> None:
    # The desk's `PartDrafts` reads each schema once; the write resolves it again, and another
    # request made a new attribute required in between.
    world = World()
    desk = desk_of(world)
    await desk.review(RESISTOR)
    world.add_attribute(world.resistors, "tolerance", required=True)

    with pytest.raises(IntakeRefusedError, match="tolerance is required") as refused:
        await desk.define(RESISTOR)

    assert found(refused.value.problems) == [(None, None, ProblemCode.INVALID)]
    assert world.catalog.parts.saved == {}
