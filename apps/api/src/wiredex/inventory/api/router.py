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

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.inventory.api.schemas import (
    AdjustRequest,
    BalanceResponse,
    CreateLocationRequest,
    LocationNodeResponse,
    LocationResponse,
    MoveRequest,
    MoveResponse,
    PartStockResponse,
    PartTotalResponse,
    ReceiveRequest,
    UpdateLocationRequest,
)
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
from wiredex.inventory.domain.errors import (
    ConcurrentStockError,
    DuplicateLocationNameError,
    InsufficientStockError,
    InventoryError,
    LocationInUseError,
    LocationNotFoundError,
    LotNotFoundError,
    PartNotFoundError,
)
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.values import (
    LocationId,
    LocationName,
    MovementReason,
    Note,
    PartId,
    Quantity,
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


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's error table, leaf by leaf. Anything else an inventory rule refuses — a bad
# name, a negative quantity, a move to the same location, an unknown reason — is the
# request's content being unprocessable, so 422.
_STATUS_BY_ERROR: Mapping[type[InventoryError], int] = {
    LocationNotFoundError: status.HTTP_404_NOT_FOUND,
    PartNotFoundError: status.HTTP_404_NOT_FOUND,
    LotNotFoundError: status.HTTP_404_NOT_FOUND,
    DuplicateLocationNameError: status.HTTP_409_CONFLICT,
    LocationInUseError: status.HTTP_409_CONFLICT,
    InsufficientStockError: status.HTTP_409_CONFLICT,
    ConcurrentStockError: status.HTTP_409_CONFLICT,
}
REFUSED = status.HTTP_422_UNPROCESSABLE_CONTENT


def create_router(
    use_cases: InventoryUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/inventory", tags=["inventory"])
    _add_location_routes(router, use_cases, current_workspace)
    _add_movement_routes(router, use_cases, current_workspace)
    _add_stock_routes(router, use_cases, current_workspace)
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


def _note(value: str | None) -> Note | None:
    return None if value is None else Note(value)
