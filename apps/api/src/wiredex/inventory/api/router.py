"""Inventory over HTTP: the location tree, the three movements, and stock per part.

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. Inventory never imports identity or
catalog — `bootstrap/app.py` builds `current_workspace` from the session use cases and the
`Parts` port over catalog, and hands both over (design §3, the independence contract).
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from wiredex.inventory.api.schemas import (
    AdjustRequest,
    BalanceResponse,
    CreateLocationRequest,
    ImportPreviewResponse,
    ImportRequest,
    ImportResultResponse,
    ImportSheetRequest,
    IntakeRefusalResponse,
    LocationNodeResponse,
    LocationResponse,
    MoveRequest,
    MoveResponse,
    MoveUnitRequest,
    PartStockResponse,
    PartTakenResponse,
    PartTotalResponse,
    QuickAddRequest,
    QuickAddResponse,
    QuickPartBody,
    ReceiveRequest,
    ReceiveUnitsRequest,
    ReceiveUnitsResponse,
    RelabelUnitRequest,
    RetireUnitRequest,
    SheetRefusalResponse,
    UnitResponse,
    UpdateLocationRequest,
)
from wiredex.inventory.application.imports import ImportSheet, PreviewImport
from wiredex.inventory.application.intake import QuickAdd, QuickAddition, QuickStock
from wiredex.inventory.application.locations import (
    CreateLocation,
    DeleteLocation,
    ListLocations,
    MoveLocation,
    RenameLocation,
)
from wiredex.inventory.application.movements import AdjustStock, MoveStock, ReceiveStock
from wiredex.inventory.application.ports import (
    Adjustment,
    Move,
    NewLocation,
    Receipt,
)
from wiredex.inventory.application.stock import PartStock, PartTotals
from wiredex.inventory.application.units import (
    DeleteUnit,
    GetUnit,
    ListUnitsOfLocation,
    ListUnitsOfPart,
    LocateUnits,
    MoveUnit,
    NewUnit,
    ReceiveUnits,
    RelabelUnit,
    RetireUnit,
    SearchUnits,
    UnitReceipt,
    UnretireUnit,
)
from wiredex.inventory.domain.errors import (
    ConcurrentStockError,
    DuplicateLocationNameError,
    DuplicateMacError,
    DuplicateSerialError,
    ImportChangedError,
    InsufficientStockError,
    IntakeRefusedError,
    InventoryError,
    LocationInUseError,
    LocationNotFoundError,
    LotNotFoundError,
    PartAlreadyDefinedError,
    PartNotFoundError,
    SheetUnreadableError,
    UnitNotFoundError,
    UnitNotRetiredError,
)
from wiredex.inventory.domain.intake import PartDraft
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.sheet import template_sheet, write_sheet
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    Mac,
    MovementReason,
    Note,
    PartId,
    Quantity,
    Serial,
    UnitId,
    WorkspaceId,
)

# A page's worth of ids the parts list asks totals for, capped: a query string with a
# thousand ids is a mistake, not a request.
MAX_STOCK_BATCH = 200


@dataclass(frozen=True, slots=True)
class InventoryUseCases:
    create_location: CreateLocation
    rename_location: RenameLocation
    move_location: MoveLocation
    delete_location: DeleteLocation
    list_locations: ListLocations
    receive_stock: ReceiveStock
    adjust_stock: AdjustStock
    move_stock: MoveStock
    part_stock: PartStock
    part_totals: PartTotals
    receive_units: ReceiveUnits
    relabel_unit: RelabelUnit
    retire_unit: RetireUnit
    unretire_unit: UnretireUnit
    move_unit: MoveUnit
    delete_unit: DeleteUnit
    get_unit: GetUnit
    list_units_of_part: ListUnitsOfPart
    list_units_of_location: ListUnitsOfLocation
    search_units: SearchUnits
    locate_units: LocateUnits
    quick_add: QuickAdd
    preview_import: PreviewImport
    import_sheet: ImportSheet


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's error table, leaf by leaf. Anything else an inventory rule refuses — a bad
# name, a negative quantity, a move to the same location, an unknown reason — is the
# request's content being unprocessable, so 422.
_STATUS_BY_ERROR: Mapping[type[InventoryError], int] = {
    LocationNotFoundError: status.HTTP_404_NOT_FOUND,
    PartNotFoundError: status.HTTP_404_NOT_FOUND,
    LotNotFoundError: status.HTTP_404_NOT_FOUND,
    UnitNotFoundError: status.HTTP_404_NOT_FOUND,
    DuplicateLocationNameError: status.HTTP_409_CONFLICT,
    LocationInUseError: status.HTTP_409_CONFLICT,
    InsufficientStockError: status.HTTP_409_CONFLICT,
    ConcurrentStockError: status.HTTP_409_CONFLICT,
    DuplicateSerialError: status.HTTP_409_CONFLICT,
    DuplicateMacError: status.HTTP_409_CONFLICT,
    UnitNotRetiredError: status.HTTP_409_CONFLICT,
    # Intake's (07): `_structured_refusals` answers the part that holds a number with its
    # structure first, so this entry only keeps its status right should it ever get here.
    PartAlreadyDefinedError: status.HTTP_409_CONFLICT,
    ImportChangedError: status.HTTP_409_CONFLICT,
    # ReceiveAsLotError and SameLocationError, like any other bad value (a malformed MAC, an
    # empty serial, a retired unit asked to move), fall through to 422 (design's error table),
    # and so do intake's problems and an unreadable sheet.
}
REFUSED = status.HTTP_422_UNPROCESSABLE_CONTENT

# The import template's file name, as the browser saves it.
_TEMPLATE_FILE = "wiredex-import.csv"


def create_router(
    use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/inventory", tags=["inventory"])
    _add_location_routes(router, use_cases, current_workspace)
    _add_movement_routes(router, use_cases, current_workspace)
    _add_stock_routes(router, use_cases, current_workspace)
    _add_unit_routes(router, use_cases, current_workspace)
    _add_intake_routes(router, use_cases, current_workspace)
    return router


def _add_location_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    @router.get("/locations")
    async def list_locations(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[LocationNodeResponse]:
        """The whole tree, flat, each location with its child and lot counts."""
        nodes = await use_cases.list_locations(workspace_id)
        return [LocationNodeResponse.from_node(node) for node in nodes]

    @router.post("/locations", status_code=status.HTTP_201_CREATED)
    async def create_location(
        body: CreateLocationRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> LocationResponse:
        """A new location, at the root when no parent is named, its short code minted."""
        with _refusals():
            new = NewLocation(LocationName(body.name), _location_id(body.parent_id))
            location = await use_cases.create_location(workspace_id, new)
        return LocationResponse.from_location(location)

    @router.patch("/locations/{location_id}")
    async def update_location(
        location_id: UUID,
        body: UpdateLocationRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> LocationResponse:
        """Rename a location, move it, or both. A no-op changes nothing; the code is kept."""
        with _refusals():
            location = await _update_location(
                use_cases, workspace_id, LocationId(location_id), body
            )
        return LocationResponse.from_location(location)

    @router.delete("/locations/{location_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_location(
        location_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Deletes an empty location. Refuses one that has children or holds lots (1.10)."""
        with _refusals():
            await use_cases.delete_location(workspace_id, LocationId(location_id))


def _add_movement_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Receive, adjust and move: the three movements this release records (design §Use cases).

    Each answers with the resulting balance so the web updates without a refetch; a move
    answers both lots'. All three are POSTs, so they carry the CSRF header like every unsafe
    method (ADR 0008), which the auth test covers.
    """

    @router.post("/receive", status_code=status.HTTP_201_CREATED)
    async def receive_stock(
        body: ReceiveRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> BalanceResponse:
        """Append a RECEIVE into (part, location) and answer the lot's new balance."""
        with _refusals():
            receipt = Receipt(
                PartId(body.part_id),
                LocationId(body.location_id),
                Quantity(body.quantity),
                _note(body.note),
            )
            balance = await use_cases.receive_stock(workspace_id, receipt)
        return BalanceResponse.from_balance(balance)

    @router.post("/adjust")
    async def adjust_stock(
        body: AdjustRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> BalanceResponse:
        """Recount a lot to an absolute counted quantity and answer its new balance."""
        with _refusals():
            adjustment = Adjustment(
                PartId(body.part_id),
                LocationId(body.location_id),
                Quantity(body.counted),
                MovementReason(body.reason),
                _note(body.note),
            )
            balance = await use_cases.adjust_stock(workspace_id, adjustment)
        return BalanceResponse.from_balance(balance)

    @router.post("/move")
    async def move_stock(
        body: MoveRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> MoveResponse:
        """Move a quantity between two locations and answer both lots' balances."""
        with _refusals():
            move = Move(
                PartId(body.part_id),
                LocationId(body.from_location_id),
                LocationId(body.to_location_id),
                Quantity(body.quantity),
                _note(body.note),
            )
            source, destination = await use_cases.move_stock(workspace_id, move)
        return MoveResponse.from_balances(source, destination)


def _add_stock_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """A page of parts' totals in one call, and one part's breakdown by location.

    The batch route takes the ids of the parts on the current page as repeated `part_id`
    query parameters, so the parts list never loads a balance per row (requirements 7.1, 7.2).
    """

    @router.get("/parts/stock")
    async def parts_stock(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        part_id: Annotated[list[UUID], Query(max_length=MAX_STOCK_BATCH)],
    ) -> list[PartTotalResponse]:
        """The total on_hand for each part asked about; a part with none is simply absent."""
        with _refusals():
            totals = await use_cases.part_totals(workspace_id, [PartId(pid) for pid in part_id])
        return [PartTotalResponse(part_id=part, on_hand=total) for part, total in totals.items()]

    @router.get("/parts/{part_id}/stock")
    async def part_stock(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PartStockResponse:
        """One part's total and its per-location breakdown; zero and empty when never held."""
        with _refusals():
            view = await use_cases.part_stock(workspace_id, PartId(part_id))
        return PartStockResponse.from_view(view)


def _add_unit_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The ten unit routes: receive, the two listings, search, one unit, and its five actions.

    Split into reads and the two write halves so each stays a small factory (the other `_add_*`
    routers are the same size). A unit's location is its lot's location, which the reads
    resolve for display through `locate_units` (design's HTTP API). Every write is a
    POST/PATCH/DELETE, so it carries the CSRF header like the movements (ADR 0008), which the
    auth test covers. Refusals turn into the design's statuses through `_refusals`.
    """
    _add_unit_read_routes(router, use_cases, current_workspace)
    _add_unit_receive_and_label_routes(router, use_cases, current_workspace)
    _add_unit_lifecycle_routes(router, use_cases, current_workspace)


def _add_unit_read_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Search, the two listings and one unit, each row carrying its resolved location (6.1-6.3)."""

    @router.get("/units")
    async def search_units(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        search: Annotated[str, Query()] = "",
    ) -> list[UnitResponse]:
        """Units matching a code/serial/MAC substring, each with its location (6.3, 2.5)."""
        found = await use_cases.search_units(workspace_id, search)
        return await _unit_rows(use_cases, workspace_id, found)

    @router.get("/parts/{part_id}/units")
    async def units_of_part(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[UnitResponse]:
        """The part's units, each with code, serial, MAC, status and location (6.1)."""
        found = await use_cases.list_units_of_part(workspace_id, PartId(part_id))
        return await _unit_rows(use_cases, workspace_id, found)

    @router.get("/locations/{location_id}/units")
    async def units_of_location(
        location_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[UnitResponse]:
        """The units sitting in the location, across every lot there (requirement 6.2)."""
        found = await use_cases.list_units_of_location(workspace_id, LocationId(location_id))
        return await _unit_rows(use_cases, workspace_id, found)

    @router.get("/units/{unit_id}")
    async def get_unit(
        unit_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> UnitResponse:
        """One unit, or 404 for one this workspace doesn't hold (requirement 7.2)."""
        with _refusals():
            unit = await use_cases.get_unit(workspace_id, UnitId(unit_id))
            location = await _location_of(use_cases, workspace_id, unit)
        return UnitResponse.of(unit, location)


def _add_unit_receive_and_label_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Receive units, relabel one, and move one — the writes that answer the changed unit."""

    @router.post("/units", status_code=status.HTTP_201_CREATED)
    async def receive_units(
        body: ReceiveUnitsRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> ReceiveUnitsResponse:
        """Receive N units of a unit-tracked part; answer the units and the lot's balance."""
        with _refusals():
            receipt = UnitReceipt(
                part_id=PartId(body.part_id),
                location_id=LocationId(body.location_id),
                units=tuple(_new_unit(entry.serial, entry.mac) for entry in body.units),
            )
            received = await use_cases.receive_units(workspace_id, receipt)
            location = await _location_of(use_cases, workspace_id, received.units[0])
        return ReceiveUnitsResponse.of(received, location)

    @router.patch("/units/{unit_id}")
    async def relabel_unit(
        unit_id: UUID,
        body: RelabelUnitRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> UnitResponse:
        """Set a unit's serial and MAC, refusing a duplicate; a no-op changes nothing (5.6)."""
        with _refusals():
            unit = await use_cases.relabel_unit(
                workspace_id, UnitId(unit_id), _serial(body.serial), _mac(body.mac)
            )
            location = await _location_of(use_cases, workspace_id, unit)
        return UnitResponse.of(unit, location)

    @router.post("/units/{unit_id}/move")
    async def move_unit(
        unit_id: UUID,
        body: MoveUnitRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> UnitResponse:
        """Move a unit to a destination location, 422 if retired or already there (4.4, 4.5)."""
        with _refusals():
            unit = await use_cases.move_unit(
                workspace_id, UnitId(unit_id), LocationId(body.to_location_id)
            )
            location = await _location_of(use_cases, workspace_id, unit)
        return UnitResponse.of(unit, location)


def _add_unit_lifecycle_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Retire, un-retire and delete — the stock-neutral status switches and the final removal."""

    @router.post("/units/{unit_id}/retire")
    async def retire_unit(
        unit_id: UUID,
        body: RetireUnitRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> UnitResponse:
        """Retire a unit, writing the compensating ADJUST -1; a retired unit is a no-op (3.1)."""
        with _refusals():
            unit = await use_cases.retire_unit(
                workspace_id, UnitId(unit_id), MovementReason(body.reason)
            )
            location = await _location_of(use_cases, workspace_id, unit)
        return UnitResponse.of(unit, location)

    @router.post("/units/{unit_id}/unretire")
    async def unretire_unit(
        unit_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> UnitResponse:
        """Un-retire a unit, writing the compensating ADJUST +1; in-stock is a no-op (3.2)."""
        with _refusals():
            unit = await use_cases.unretire_unit(workspace_id, UnitId(unit_id))
            location = await _location_of(use_cases, workspace_id, unit)
        return UnitResponse.of(unit, location)

    @router.delete("/units/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_unit(
        unit_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Delete a retired unit; an in-stock one is a 409 (requirement 6.4)."""
        with _refusals():
            await use_cases.delete_unit(workspace_id, UnitId(unit_id))


def _add_intake_routes(
    router: APIRouter, use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Quick-add, and a sheet's preview, import and template (design's HTTP API).

    The three POSTs carry the CSRF header like every unsafe method, and the template's GET
    needs a session like every read (ADR 0008): both checks come with `current_workspace`,
    which the auth test covers. Refusals with a structure (every problem, the part holding a
    number, an unreadable sheet's code) go through `_structured_refusals()` inside
    `_refusals()`, so no other route changes shape. Units answer with their locations, as the
    unit receive's do.
    """

    @router.post("/quick-add", status_code=status.HTTP_201_CREATED)
    async def quick_add(
        body: QuickAddRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> QuickAddResponse:
        """Define a part and receive its first stock in one transaction (requirement 1).

        422 with every problem at once, 409 naming the part that holds the manufacturer and
        part number, 404 for a duplicate's source the workspace doesn't hold (3.4).
        """
        with _refusals(), _structured_refusals():
            added = await use_cases.quick_add(workspace_id, _quick_addition(body))
            units = await _unit_rows(use_cases, workspace_id, list(added.units))
        return QuickAddResponse.of(added, units)

    @router.post("/imports/preview")
    async def preview_import(
        body: ImportSheetRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> ImportPreviewResponse:
        """What every row of the sheet will do, writing nothing (requirement 7).

        A plan with problems is still a 200: finding them is what a preview is for (7.5).
        Only a sheet that can't be read at all is a 422, with its code and column (4.6).
        """
        with _refusals(), _structured_refusals():
            plan = await use_cases.preview_import(workspace_id, body.csv)
        return ImportPreviewResponse.from_plan(plan)

    @router.post("/imports", status_code=status.HTTP_201_CREATED)
    async def import_sheet(
        body: ImportRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> ImportResultResponse:
        """Import the sheet its preview showed, all in one transaction (requirement 8).

        422 with the problems when the plan has any, 409 when the outcome changed since the
        preview's digest; either way nothing is written (8.2, 8.3).
        """
        with _refusals(), _structured_refusals():
            result = await use_cases.import_sheet(workspace_id, body.csv, body.digest)
            units = await _unit_rows(use_cases, workspace_id, list(result.units))
        return ImportResultResponse.of(result, units)

    @router.get(
        "/imports/template",
        dependencies=[Depends(current_workspace)],
        response_class=Response,
        responses={status.HTTP_200_OK: {"content": {"text/csv": {"schema": {"type": "string"}}}}},
    )
    async def import_template() -> Response:
        """The header row of the nine fixed columns, as a CSV download (requirement 4.9).

        Reads no workspace, but only a signed-in caller gets it, as every other read.
        """
        return Response(
            write_sheet(template_sheet()),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{_TEMPLATE_FILE}"'},
        )


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns an inventory refusal into the status the design's table gives it.

    One place rather than a handler full of `except` clauses, and no global handler: the
    mapping is part of this router's contract, not the application's, as catalog's is.
    """
    try:
        yield
    except InventoryError as error:
        raise HTTPException(_status_of(error), str(error)) from error


@contextmanager
def _structured_refusals() -> Iterator[None]:
    """An intake refusal answered with its structure instead of a sentence (design's Error
    Handling): every problem with its row, column and code; an unreadable sheet's code and
    column; the part that already holds a number, so the web can link to it.

    Nested inside `_refusals()` and never outside it, as catalog's `_refused_rows()` is: these
    are `InventoryError`s too, so the structured detail has to be built first, or the generic
    mapping would flatten it to a message and the web would have no field to mark. Every
    other refusal falls through to that mapping.
    """
    try:
        yield
    except IntakeRefusedError as error:
        refusal = IntakeRefusalResponse.from_error(error)
        raise HTTPException(REFUSED, refusal.model_dump(mode="json")) from error
    except SheetUnreadableError as error:
        unreadable = SheetRefusalResponse.from_error(error)
        raise HTTPException(REFUSED, unreadable.model_dump(mode="json")) from error
    except PartAlreadyDefinedError as error:
        taken = PartTakenResponse.from_error(error)
        raise HTTPException(status.HTTP_409_CONFLICT, taken.model_dump(mode="json")) from error


def _status_of(error: InventoryError) -> int:
    for kind in type(error).__mro__:
        found = _STATUS_BY_ERROR.get(kind)
        if found is not None:
            return found
    return REFUSED


async def _update_location(
    use_cases: InventoryUseCases,
    workspace_id: WorkspaceId,
    location_id: LocationId,
    body: UpdateLocationRequest,
) -> Location:
    """Applies what the patch carried, in the order a form sends it: name, then parent.

    `parent_id: null` is a move to the root, so what the body carried is read from the fields
    it set and not from their values, as catalog's category patch does. The last operation's
    location is answered; a patch carrying neither is refused.
    """
    location = None
    if body.name is not None:
        location = await use_cases.rename_location(
            workspace_id, location_id, LocationName(body.name)
        )
    if body.moves():
        location = await use_cases.move_location(
            workspace_id, location_id, _location_id(body.parent_id)
        )
    if location is None:
        raise HTTPException(REFUSED, "a patch has to carry a name or a parent")
    return location


def _location_id(value: UUID | None) -> LocationId | None:
    return None if value is None else LocationId(value)


def _quick_addition(body: QuickAddRequest) -> QuickAddition:
    """A quick-add from the wire: the part as typed, its stock, and a duplicate's source.

    Nothing is read here beyond the ids: the catalog reviews the part and the use case the
    stock, so every problem comes back together (requirement 1.5).
    """
    part = body.part
    draft = PartDraft(
        category_id=part.category_id,
        name=part.name,
        manufacturer=part.manufacturer,
        mpn=part.mpn,
        package=part.package,
        attributes=_given_attributes(part),
    )
    stock = body.stock
    return QuickAddition(
        draft,
        None if stock is None else QuickStock(LocationId(stock.location_id), stock.quantity),
        None if body.pinout_from is None else PartId(body.pinout_from),
    )


def _given_attributes(part: QuickPartBody) -> dict[str, str | bool]:
    """The attribute values given: null or blank text is nothing given, as a blank cell of a
    sheet is, so a required one left empty is `missing` rather than a refused value."""
    given: dict[str, str | bool] = {}
    for key, value in part.attributes.items():
        if isinstance(value, bool) or (value is not None and value.strip()):
            given[key] = value
    return given


def _note(value: str | None) -> Note | None:
    return None if value is None else Note(value)


def _new_unit(serial: str | None, mac: str | None) -> NewUnit:
    """One receipt entry from the wire: a bad serial or MAC is a value refusal (a 422 here)."""
    return NewUnit(serial=_serial(serial), mac=_mac(mac))


def _serial(value: str | None) -> Serial | None:
    return None if value is None else Serial(value)


def _mac(value: str | None) -> Mac | None:
    return None if value is None else Mac(value)


async def _unit_rows(
    use_cases: InventoryUseCases, workspace_id: WorkspaceId, units: list[Unit]
) -> list[UnitResponse]:
    """Turn units into rows, resolving each one's location for display (6.1, 6.3).

    The location is the unit's lot's location; `locate_units` reads each distinct lot once, so
    a listing of many units at a few locations costs a handful of reads, not one per unit.
    """
    locations = await use_cases.locate_units(workspace_id, units)
    return [UnitResponse.of(unit, locations.get(unit.id)) for unit in units]


async def _location_of(
    use_cases: InventoryUseCases, workspace_id: WorkspaceId, unit: Unit
) -> Location | None:
    """The one unit's location, for the routes that answer a single unit."""
    located = await use_cases.locate_units(workspace_id, [unit])
    return located.get(unit.id)
