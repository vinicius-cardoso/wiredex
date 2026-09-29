"""One transaction across projects and catalog, for a netlist read or write.

The one file that sees both modules for the netlist (11-netlist-editor decision 1, requirement
11.1). Projects declares `NetlistPins` and reuses 10's `BuildParts`, as properties of its
`NetlistUnitOfWork`, and imports nothing from catalog. Catalog offers `pinouts_of` and
`describe_parts` over a `CatalogRepositories`, which never opens or commits a transaction of its
own. This file joins them: the third use of 07's shared-session pattern, after
`bootstrap/intake.py` and `bootstrap/build.py`.

A net write reads the BOM under the project's lock and the pinouts it checks new references
against in that same transaction, on that same connection, under the one workspace setting the
projects unit of work applied, so row-level security scopes both modules' rows (requirement
8.3). Nothing locks catalog's rows: a pinout replaced a moment after a write only turns a
reference unresolved, which the owner's decision makes a state, not a fault.
"""

from collections.abc import Collection
from typing import Self

from wiredex.bootstrap.build import CatalogBuildParts
from wiredex.catalog.application.pinouts import pinouts_of
from wiredex.catalog.application.ports import CatalogRepositories
from wiredex.catalog.domain.pinout import Pin, Pinout
from wiredex.catalog.domain.values import PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogRepositories
from wiredex.projects.domain.pins import PartPins, PinFacts, PinNumber, PinType
from wiredex.projects.domain.values import PartId
from wiredex.projects.infrastructure.unit_of_work import SqlProjectsUnitOfWork


class CatalogNetlistPins:
    """Projects' `NetlistPins` over catalog's `pinouts_of`, on the netlist's session.

    Catalog's `Pin` becomes projects' `PinFacts`: its number through projects' own `PinNumber`,
    which normalizes exactly as catalog's does (decision 13, pinned by a test), its type by
    value, its label and functions as text, and its voltage as the exact `Decimal` it holds.
    """

    def __init__(self, repositories: CatalogRepositories) -> None:
        self._repositories = repositories

    async def of_parts(self, part_ids: Collection[PartId]) -> dict[PartId, PartPins]:
        found = await pinouts_of(
            self._repositories, [PartDefinitionId(part_id) for part_id in part_ids]
        )
        return {PartId(part_id): _part_pins(pinout) for part_id, pinout in found.items()}


class SqlNetlistUnitOfWork(SqlProjectsUnitOfWork):
    """The projects unit of work with catalog's parts and pins on its session.

    A `NetlistUnitOfWork`: the base opens the session, sets `app.workspace_id` for the
    transaction and binds projects' repositories, 09's `bom_lines` and 11's `nets`. Catalog's
    repositories then join that same session under the same workspace, wrapped as 10's
    `CatalogBuildParts` and `CatalogNetlistPins`. Commit and rollback stay 08's.
    """

    parts: CatalogBuildParts
    pins: CatalogNetlistPins

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        # The same UUID under each module's own name: neither imports the other's domain.
        catalog = SqlCatalogRepositories(self.session, CatalogWorkspaceId(self._workspace))
        self.parts = CatalogBuildParts(catalog)
        self.pins = CatalogNetlistPins(catalog)
        return self


def _part_pins(pinout: Pinout) -> PartPins:
    return PartPins(tuple(_pin_facts(pin) for pin in pinout))


def _pin_facts(pin: Pin) -> PinFacts:
    return PinFacts(
        number=PinNumber(str(pin.number)),
        label=str(pin.label),
        type=PinType(pin.type.value),
        functions=tuple(str(function) for function in pin.functions),
        voltage=None if pin.voltage is None else pin.voltage.value,
    )
