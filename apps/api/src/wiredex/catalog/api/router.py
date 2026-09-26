"""The catalog over HTTP: the category tree, the fields a category declares, and its parts.

A factory, as the other routers are: the use cases and the workspace dependency come in as
arguments, so the composition root decides what runs. Catalog never imports identity —
`bootstrap/app.py` builds `current_workspace` from the session use cases and hands it over
(design §3).
"""

from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from wiredex.catalog.api.schemas import (
    AttributeResponse,
    BoolFilterRequest,
    CategoryNodeResponse,
    CategoryResponse,
    CategorySchemaResponse,
    CreateCategoryRequest,
    DefineAttributeRequest,
    DefinePartRequest,
    FacetsResponse,
    FilterRequest,
    OptionsFilterRequest,
    PartPageResponse,
    PartResponse,
    PartSearchRequest,
    PartSearchResponse,
    PinoutRefusalResponse,
    PinoutResponse,
    RangeFilterRequest,
    ReplacePinoutRequest,
    UpdateAttributeRequest,
    UpdateCategoryRequest,
    UpdatePartRequest,
)
from wiredex.catalog.application.attributes import (
    AttributeChanges,
    DefineAttribute,
    GetCategorySchema,
    NewAttribute,
    RemoveAttribute,
    UpdateAttribute,
)
from wiredex.catalog.application.categories import (
    CreateCategory,
    DeleteCategory,
    ListCategories,
    MoveCategory,
    NewCategory,
    RenameCategory,
)
from wiredex.catalog.application.parts import (
    DefinePart,
    DeletePart,
    GetPart,
    ListParts,
    NewPart,
    PartRevision,
    PartView,
    UpdatePart,
)
from wiredex.catalog.application.pinouts import GetPinout, ReplacePinout
from wiredex.catalog.application.ports import DEFAULT_PAGE_SIZE, PartQuery
from wiredex.catalog.application.search import (
    CategoryFacets,
    PartSearch,
    RawFilter,
    SearchParts,
)
from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.errors import (
    AttributeNotFoundError,
    CatalogError,
    CategoryInUseError,
    CategoryNotFoundError,
    DuplicateAttributeKeyError,
    DuplicateCategoryNameError,
    DuplicateMpnError,
    InvalidPinoutError,
    PartNotFoundError,
)
from wiredex.catalog.domain.part import PartDetails
from wiredex.catalog.domain.pinout import RawPin
from wiredex.catalog.domain.schema import AttributeSchema
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

# A page the caller asks for, capped: a limit of a million is a mistake, not a request.
MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class CatalogUseCases:
    create_category: CreateCategory
    rename_category: RenameCategory
    move_category: MoveCategory
    delete_category: DeleteCategory
    list_categories: ListCategories
    define_attribute: DefineAttribute
    update_attribute: UpdateAttribute
    remove_attribute: RemoveAttribute
    get_category_schema: GetCategorySchema
    define_part: DefinePart
    update_part: UpdatePart
    get_part: GetPart
    list_parts: ListParts
    delete_part: DeletePart
    get_pinout: GetPinout
    replace_pinout: ReplacePinout
    search_parts: SearchParts
    category_facets: CategoryFacets


type CurrentWorkspaceDependency = Callable[[Request], Awaitable[WorkspaceId]]

# The design's error table, leaf by leaf. Anything else a catalog rule refuses — a bad
# number, an unknown key, a missing required value, a cycle, a tree too deep — is the
# request's content being unprocessable, so 422.
_STATUS_BY_ERROR: Mapping[type[CatalogError], int] = {
    CategoryNotFoundError: status.HTTP_404_NOT_FOUND,
    AttributeNotFoundError: status.HTTP_404_NOT_FOUND,
    PartNotFoundError: status.HTTP_404_NOT_FOUND,
    DuplicateCategoryNameError: status.HTTP_409_CONFLICT,
    DuplicateAttributeKeyError: status.HTTP_409_CONFLICT,
    DuplicateMpnError: status.HTTP_409_CONFLICT,
    CategoryInUseError: status.HTTP_409_CONFLICT,
}
REFUSED = status.HTTP_422_UNPROCESSABLE_CONTENT


def create_router(
    use_cases: CatalogUseCases, current_workspace: CurrentWorkspaceDependency
) -> APIRouter:
    router = APIRouter(prefix="/catalog", tags=["catalog"])
    _add_category_routes(router, use_cases, current_workspace)
    _add_attribute_routes(router, use_cases, current_workspace)
    _add_part_routes(router, use_cases, current_workspace)
    _add_pinout_routes(router, use_cases, current_workspace)
    _add_search_routes(router, use_cases, current_workspace)
    return router


def _add_category_routes(
    router: APIRouter, use_cases: CatalogUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    @router.get("/categories")
    async def list_categories(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> list[CategoryNodeResponse]:
        """The whole tree, flat, each category with its child and part counts."""
        nodes = await use_cases.list_categories(workspace_id)
        return [CategoryNodeResponse.from_node(node) for node in nodes]

    @router.post("/categories", status_code=status.HTTP_201_CREATED)
    async def create_category(
        body: CreateCategoryRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> CategoryResponse:
        """A new category, at the root when no parent is named."""
        with _refusals():
            new = NewCategory(CategoryName(body.name), _category_id(body.parent_id))
            return CategoryResponse.from_category(
                await use_cases.create_category(workspace_id, new)
            )

    @router.patch("/categories/{category_id}")
    async def update_category(
        category_id: UUID,
        body: UpdateCategoryRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> CategoryResponse:
        """Rename a category, move it, or both. Renaming it to its own name changes nothing."""
        with _refusals():
            category = await _update_category(
                use_cases, workspace_id, CategoryId(category_id), body
            )
        return CategoryResponse.from_category(category)

    @router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_category(
        category_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Deletes the category and its own attribute definitions. Refuses one still in use."""
        with _refusals():
            await use_cases.delete_category(workspace_id, CategoryId(category_id))


def _add_attribute_routes(
    router: APIRouter, use_cases: CatalogUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    @router.get("/categories/{category_id}/schema")
    async def read_category_schema(
        category_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> CategorySchemaResponse:
        """Every field the category's parts have, inherited ones marked."""
        with _refusals():
            resolved = await use_cases.get_category_schema(workspace_id, CategoryId(category_id))
        return CategorySchemaResponse.from_schema(resolved)

    @router.post("/categories/{category_id}/attributes", status_code=status.HTTP_201_CREATED)
    async def define_attribute(
        category_id: UUID,
        body: DefineAttributeRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> AttributeResponse:
        """A new field on the category. A key an ancestor already defines is refused."""
        with _refusals():
            definition = await use_cases.define_attribute(
                workspace_id, CategoryId(category_id), _new_attribute(body)
            )
        return AttributeResponse.from_definition(definition)

    @router.patch("/attributes/{attribute_id}")
    async def update_attribute(
        attribute_id: UUID,
        body: UpdateAttributeRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> AttributeResponse:
        """Label, required, options and position. No stored part value is touched."""
        with _refusals():
            definition = await use_cases.update_attribute(
                workspace_id, AttributeDefinitionId(attribute_id), _changes(body)
            )
        return AttributeResponse.from_definition(definition)

    @router.delete("/attributes/{attribute_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def remove_attribute(
        attribute_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        """Removes the definition. The values stay, and their parts are flagged on read."""
        with _refusals():
            await use_cases.remove_attribute(workspace_id, AttributeDefinitionId(attribute_id))


def _add_part_routes(
    router: APIRouter, use_cases: CatalogUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    @router.get("/parts")
    async def list_parts(
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        q: str | None = None,
        category_id: UUID | None = None,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
        cursor: UUID | None = None,
    ) -> PartPageResponse:
        """A page of parts, narrowed by a name substring and by category."""
        query = PartQuery(_category_id(category_id), q, limit, _part_id(cursor))
        return PartPageResponse.from_page(await use_cases.list_parts(workspace_id, query))

    @router.post("/parts", status_code=status.HTTP_201_CREATED)
    async def define_part(
        body: DefinePartRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PartResponse:
        """A new part, with every value validated against its category's resolved schema."""
        with _refusals():
            part = await use_cases.define_part(workspace_id, _new_part(body))
            return await _read_values(use_cases, workspace_id, PartView(part))

    @router.get("/parts/{part_id}")
    async def read_part(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PartResponse:
        """One part. A part whose values no longer fit is returned, marked for review."""
        with _refusals():
            view = await use_cases.get_part(workspace_id, PartDefinitionId(part_id))
            return await _read_values(use_cases, workspace_id, view)

    @router.patch("/parts/{part_id}")
    async def update_part(
        part_id: UUID,
        body: UpdatePartRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PartResponse:
        """Replaces the details and the whole attribute map, so nothing is saved half-valid."""
        with _refusals():
            view = await use_cases.update_part(
                workspace_id, PartDefinitionId(part_id), _revision(body)
            )
            return await _read_values(use_cases, workspace_id, view)

    @router.delete("/parts/{part_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_part(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> None:
        with _refusals():
            await use_cases.delete_part(workspace_id, PartDefinitionId(part_id))


def _add_pinout_routes(
    router: APIRouter, use_cases: CatalogUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """The part's pin table: read it, or replace the whole of it. Its own function to stay
    under the complexity cap, as the three groups above it are."""

    @router.get("/parts/{part_id}/pinout")
    async def read_pinout(
        part_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PinoutResponse:
        """The pins in their saved order. A part with none answers an empty list, not 404."""
        with _refusals():
            pinout = await use_cases.get_pinout(workspace_id, PartDefinitionId(part_id))
        return PinoutResponse.from_pinout(pinout)

    @router.put("/parts/{part_id}/pinout")
    async def replace_pinout(
        part_id: UUID,
        body: ReplacePinoutRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PinoutResponse:
        """The whole table at once, so no pinout is ever stored half-saved. No pins clears it."""
        with _refusals(), _refused_rows():
            stored = await use_cases.replace_pinout(
                workspace_id, PartDefinitionId(part_id), _rows(body)
            )
        return PinoutResponse.from_pinout(stored)


def _add_search_routes(
    router: APIRouter, use_cases: CatalogUseCases, current_workspace: CurrentWorkspaceDependency
) -> None:
    """Parametric search and its facets: a POST with a typed body, and a GET for the counts.

    Search is a POST because a list of filters is structured data, and the generated client
    then types it end to end (design's HTTP API); `GET /catalog/parts` stays for simple
    listing. A refused filter, cursor or sort is a 422 whose message names what it refuses,
    which the generic `_refusals` mapping already gives every `CatalogError`.
    """

    @router.post("/parts/search")
    async def search_parts(
        body: PartSearchRequest,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
    ) -> PartSearchResponse:
        """A page of the parts the search matches, ordered and continued from its cursor."""
        with _refusals():
            page = await use_cases.search_parts(workspace_id, _part_search(body))
            schema = await _search_columns(use_cases, workspace_id, body.category_id)
        return PartSearchResponse.from_page(page, schema)

    @router.get("/categories/{category_id}/facets")
    async def category_facets(
        category_id: UUID,
        workspace_id: Annotated[WorkspaceId, Depends(current_workspace)],
        q: str | None = None,
        pin: str | None = None,
    ) -> FacetsResponse:
        """What the category's parts hold, counted over text and pin only (requirement 5.2)."""
        with _refusals():
            facets = await use_cases.category_facets(workspace_id, CategoryId(category_id), q, pin)
        return FacetsResponse.from_facets(facets)


@contextmanager
def _refusals() -> Iterator[None]:
    """Turns a catalog refusal into the status the design's table gives it.

    One place rather than a handler full of `except` clauses, and no global handler: the
    mapping is part of this router's contract, not the application's.
    """
    try:
        yield
    except CatalogError as error:
        raise HTTPException(_status_of(error), str(error)) from error


@contextmanager
def _refused_rows() -> Iterator[None]:
    """A refused pin table, answered with the row and the cell instead of a sentence.

    Nested inside `_refusals()` and never outside it: an `InvalidPinoutError` is a
    `CatalogError` too, so the structured detail has to be built first or the generic
    mapping would flatten it to a message and the editor would have no cell to mark
    (design's "Error Handling"). Every other catalog refusal falls through to that mapping,
    so no other route changes shape.
    """
    try:
        yield
    except InvalidPinoutError as error:
        detail = PinoutRefusalResponse.from_error(error)
        raise HTTPException(REFUSED, detail.model_dump()) from error


def _status_of(error: CatalogError) -> int:
    for kind in type(error).__mro__:
        found = _STATUS_BY_ERROR.get(kind)
        if found is not None:
            return found
    return REFUSED


async def _read_values(
    use_cases: CatalogUseCases, workspace_id: WorkspaceId, view: PartView
) -> PartResponse:
    """A part with its values in wire shape, which needs the schema to label their units.

    The read is what makes `{"value": "4700", "display": "4.7k", "unit": "Ω"}` possible:
    the stored value is a bare number, and only its definition knows what it measures.
    """
    resolved = await use_cases.get_category_schema(workspace_id, view.part.category_id)
    return PartResponse.from_view(view, resolved.schema)


async def _update_category(
    use_cases: CatalogUseCases,
    workspace_id: WorkspaceId,
    category_id: CategoryId,
    body: UpdateCategoryRequest,
) -> Category:
    """Applies what the patch carried, in the order a form sends it: the name, then the parent.

    `parent_id: null` is a move to the root, so what the body carried is read from the fields
    it set and not from their values.
    """
    category = None
    if body.name is not None:
        category = await use_cases.rename_category(
            workspace_id, category_id, CategoryName(body.name)
        )
    if body.moves():
        category = await use_cases.move_category(
            workspace_id, category_id, _category_id(body.parent_id)
        )
    if category is None:
        raise HTTPException(REFUSED, "a patch has to carry a name, a parent, or both")
    return category


def _new_attribute(body: DefineAttributeRequest) -> NewAttribute:
    return NewAttribute(
        AttributeKey(body.key),
        AttributeLabel(body.label),
        AttributeKind(body.kind),
        _unit(body.unit),
        body.required,
        tuple(body.options),
        body.position,
    )


def _changes(body: UpdateAttributeRequest) -> AttributeChanges:
    return AttributeChanges(
        label=None if body.label is None else AttributeLabel(body.label),
        required=body.required,
        options=None if body.options is None else tuple(body.options),
        position=body.position,
        key=None if body.key is None else AttributeKey(body.key),
        kind=None if body.kind is None else AttributeKind(body.kind),
    )


def _new_part(body: DefinePartRequest) -> NewPart:
    details = PartDetails(
        PartName(body.name),
        _manufacturer(body.manufacturer),
        _mpn(body.mpn),
        _package(body.package),
    )
    return NewPart(CategoryId(body.category_id), details, dict(body.attributes))


def _rows(body: ReplacePinoutRequest) -> list[RawPin]:
    """The table as untyped rows, which is how far the API reads it.

    Turning text into a `PinNumber` or a `VoltageLevel` is the domain's, as it is for a
    part's attribute map: only `Pinout.parse` can refuse a row and say which one it was.
    """
    return [
        RawPin(pin.number, pin.label, pin.type, list(pin.functions), pin.voltage)
        for pin in body.pins
    ]


def _revision(body: UpdatePartRequest) -> PartRevision:
    details = PartDetails(
        PartName(body.name),
        _manufacturer(body.manufacturer),
        _mpn(body.mpn),
        _package(body.package),
    )
    return PartRevision(details, dict(body.attributes), _category_id(body.category_id))


def _part_search(body: PartSearchRequest) -> PartSearch:
    """The search body as the application's `PartSearch`, filters flattened to `RawFilter`."""
    return PartSearch(
        text=body.text,
        category_id=_category_id(body.category_id),
        exact_category=body.exact_category,
        pin=body.pin,
        filters=[_raw_filter(f) for f in body.filters],
        sort=body.sort,
        direction=body.direction,
        cursor=body.cursor,
        limit=body.limit,
    )


def _raw_filter(request: FilterRequest) -> RawFilter:
    """One filter of the discriminated union as the untyped `RawFilter` the use case reads.

    Which fields are set is what tells the kinds apart, the way the domain does: only the
    category's schema turns a `RawFilter` into a typed one, so the wire union collapses to
    the one shape that carries every kind's fields.
    """
    if isinstance(request, RangeFilterRequest):
        return RawFilter(request.key, minimum=request.minimum, maximum=request.maximum)
    if isinstance(request, OptionsFilterRequest):
        return RawFilter(request.key, options=request.options)
    if isinstance(request, BoolFilterRequest):
        return RawFilter(request.key, value=request.value)
    return RawFilter(request.key, text=request.text)


async def _search_columns(
    use_cases: CatalogUseCases, workspace_id: WorkspaceId, category_id: UUID | None
) -> AttributeSchema | None:
    """The chosen category's resolved schema, for the results' attribute columns, or `None`.

    A search with no category has no schema and so no columns (requirement 6.3); one with a
    category resolves it once, the way a part read does, so the row shows its number and enum
    values. The search itself already refused an unknown or absent category before this runs.
    """
    if category_id is None:
        return None
    resolved = await use_cases.get_category_schema(workspace_id, CategoryId(category_id))
    return resolved.schema


def _category_id(value: UUID | None) -> CategoryId | None:
    return None if value is None else CategoryId(value)


def _part_id(value: UUID | None) -> PartDefinitionId | None:
    return None if value is None else PartDefinitionId(value)


def _unit(value: str | None) -> Unit | None:
    return None if value is None else Unit(value)


def _manufacturer(value: str | None) -> Manufacturer | None:
    return None if value is None else Manufacturer(value)


def _mpn(value: str | None) -> Mpn | None:
    return None if value is None else Mpn(value)


def _package(value: str | None) -> Package | None:
    return None if value is None else Package(value)
