"""The sample catalog a demo bench holds, and putting it back (ADR 0007, requirement 6.6).

A guest may add, rename and delete whatever they like in their own bench, so restoring is
not a merge: the workspace's catalog is cleared and the sample tree written again, which is
what makes a demo bench look the same every morning.

The values are written the way they would be typed — `4k7`, `100nF` — and go through
`AttributeSchema.validate`, so the sample data is read by exactly the code a part from the
form is read by, and a spelling that stopped parsing would fail the nightly job.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from wiredex.catalog.application.categories import UnitOfWorkFactory
from wiredex.catalog.application.ports import CatalogUnitOfWork
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.schema import AttributeDefinition, AttributeSchema
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    CategoryName,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
    Unit,
    WorkspaceId,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


@dataclass(frozen=True, slots=True)
class SampleAttribute:
    """One field of the sample schema, in the words the form would show."""

    key: str
    label: str
    kind: AttributeKind
    unit: str | None = None
    required: bool = False
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SamplePart:
    """A sample part, its attribute values spelled as a person would type them."""

    name: str
    attributes: Mapping[str, object] = field(default_factory=dict)
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None


@dataclass(frozen=True, slots=True)
class SampleCategory:
    """One node of the sample tree, with the fields it declares and the parts under it."""

    name: str
    attributes: tuple[SampleAttribute, ...] = ()
    parts: tuple[SamplePart, ...] = ()
    children: tuple[SampleCategory, ...] = ()


# Small on purpose, and still enough to show what the catalog does: a tolerance inherited
# by both kinds of passive, a number attribute per kind in its own unit, and values in the
# notation they are printed in. `100nF` carries the attribute's unit, which parsing drops.
SAMPLE_CATALOG: tuple[SampleCategory, ...] = (
    SampleCategory(
        "Passives",
        attributes=(
            SampleAttribute(
                "tolerance",
                "Tolerance",
                AttributeKind.ENUM,
                options=("±1 %", "±5 %", "±10 %", "±20 %"),
            ),
        ),
        children=(
            SampleCategory(
                "Resistors",
                attributes=(
                    SampleAttribute(
                        "resistance", "Resistance", AttributeKind.NUMBER, unit="Ω", required=True
                    ),
                ),
                parts=(
                    SamplePart(
                        "Resistor 4k7 0805",
                        {"resistance": "4k7", "tolerance": "±1 %"},
                        manufacturer="Yageo",
                        mpn="RC0805FR-074K7L",
                        package="0805",
                    ),
                    SamplePart(
                        "Resistor 220R 0805",
                        {"resistance": "220R", "tolerance": "±5 %"},
                        manufacturer="Yageo",
                        mpn="RC0805JR-07220RL",
                        package="0805",
                    ),
                    SamplePart(
                        "Resistor 10k 0603",
                        {"resistance": "10k", "tolerance": "±1 %"},
                        manufacturer="Vishay",
                        mpn="CRCW060310K0FKEA",
                        package="0603",
                    ),
                ),
            ),
            SampleCategory(
                "Capacitors",
                attributes=(
                    SampleAttribute(
                        "capacitance", "Capacitance", AttributeKind.NUMBER, unit="F", required=True
                    ),
                ),
                parts=(
                    SamplePart(
                        "Capacitor 100n 0603 X7R",
                        {"capacitance": "100nF", "tolerance": "±10 %"},
                        manufacturer="Murata",
                        mpn="GRM188R71H104KA93D",
                        package="0603",
                    ),
                    SamplePart(
                        "Capacitor 2u2 0805 X5R",
                        {"capacitance": "2u2", "tolerance": "±20 %"},
                        manufacturer="Samsung",
                        mpn="CL21A225KAFNNNE",
                        package="0805",
                    ),
                ),
            ),
        ),
    ),
)


class RestoreSampleCatalog:
    """Puts one demo bench's sample catalog back, whatever the guest did to it.

    Part of the nightly `wiredex demo reset` (ADR 0011). Which workspaces are demo benches
    is identity's to answer, so the composition root asks there and hands the ids here:
    the catalog module never imports identity (design §3).
    """

    def __init__(self, unit_of_work: UnitOfWorkFactory, clock: Clock, ids: IdGenerator) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._ids = ids

    async def __call__(self, workspace_id: WorkspaceId) -> int:
        """Returns how many sample parts the bench ended up with.

        One transaction: a bench is never left half-restored, and the workspace it is
        opened for is the only one it can touch (ADR 0007).
        """
        async with self._unit_of_work(workspace_id) as work:
            await _clear(work)
            seeding = _Seeding(workspace_id, self._clock.now(), self._ids)
            for sample in SAMPLE_CATALOG:
                await seeding.write(work, sample)
            await work.commit()
            return seeding.parts


async def _clear(work: CatalogUnitOfWork) -> None:
    """Everything the bench holds, parts first: a category with parts under it can't go."""
    await work.parts.remove_all()
    await work.attribute_definitions.remove_all()
    await work.categories.remove_all()


class _Seeding:
    """One pass over the sample tree, carrying what every row it writes needs.

    The schema chain is built as it walks rather than read back, because a category's own
    definitions were just written here: the walk already knows what a part's values are
    measured against.
    """

    def __init__(self, workspace_id: WorkspaceId, now: datetime, ids: IdGenerator) -> None:
        self._workspace_id = workspace_id
        self._now = now
        self._ids = ids
        self.parts = 0

    async def write(
        self,
        work: CatalogUnitOfWork,
        sample: SampleCategory,
        parent: Category | None = None,
        inherited: Sequence[Iterable[AttributeDefinition]] = (),
    ) -> None:
        """Writes a sample category, its fields, its parts, then everything under it."""
        category = Category(
            CategoryId(self._ids.new_id()),
            self._workspace_id,
            None if parent is None else parent.id,
            CategoryName(sample.name),
            self._now,
        )
        await work.categories.add(category)
        definitions = [
            self._definition(category, position, attribute)
            for position, attribute in enumerate(sample.attributes)
        ]
        for definition in definitions:
            await work.attribute_definitions.add(definition)
        chain = [*inherited, definitions]
        schema = AttributeSchema.inherited(chain)
        for part in sample.parts:
            await self._part(work, category, part, schema)
        for child in sample.children:
            await self.write(work, child, category, chain)

    def _definition(
        self, category: Category, position: int, attribute: SampleAttribute
    ) -> AttributeDefinition:
        return AttributeDefinition(
            AttributeDefinitionId(self._ids.new_id()),
            category.workspace_id,
            category.id,
            AttributeKey(attribute.key),
            AttributeLabel(attribute.label),
            attribute.kind,
            None if attribute.unit is None else Unit(attribute.unit),
            attribute.required,
            attribute.options,
            position,
        )

    async def _part(
        self,
        work: CatalogUnitOfWork,
        category: Category,
        sample: SamplePart,
        schema: AttributeSchema,
    ) -> None:
        part = PartDefinition.define(
            PartDefinitionId(self._ids.new_id()),
            category,
            _details(sample),
            # The same validation a part from the form goes through, which is what turns
            # "4k7" into 4700 and refuses a unit that isn't the attribute's.
            schema.validate(sample.attributes),
            self._now,
        )
        await work.parts.add(part)
        self.parts += 1


def _details(sample: SamplePart) -> PartDetails:
    return PartDetails(
        PartName(sample.name),
        None if sample.manufacturer is None else Manufacturer(sample.manufacturer),
        None if sample.mpn is None else Mpn(sample.mpn),
        None if sample.package is None else Package(sample.package),
    )
