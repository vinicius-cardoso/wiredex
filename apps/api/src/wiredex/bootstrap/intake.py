"""One transaction across catalog and inventory, for quick-add and sheet import.

The one file that knows both modules' intake halves (design decision 2). Inventory declares
the `PartCatalog` port as a property of its `IntakeUnitOfWork` and never imports catalog.
Catalog offers `PartDrafts`, which never opens or commits a unit of work. This file joins
them. `SqlIntakeUnitOfWork` opens one session, scopes it to the workspace once and binds
inventory's repositories to it, as every inventory unit of work does. Then it binds
`CatalogPartDesk` to the same session, so one `commit()` keeps a part and its stock and
leaving without it keeps neither (requirements 1.4, 8.4, 12.1).
"""

from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wiredex.catalog.application.drafts import DraftReview, PartDrafts, RawPartDraft
from wiredex.catalog.domain.errors import (
    CatalogError,
    CategoryNotFoundError,
    DraftProblem,
    DraftRefusedError,
    DuplicateMpnError,
)
from wiredex.catalog.domain.errors import PartNotFoundError as SourceNotFoundError
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.values import CategoryId, PartDefinitionId
from wiredex.catalog.domain.values import WorkspaceId as CatalogWorkspaceId
from wiredex.catalog.infrastructure.unit_of_work import SqlCatalogRepositories
from wiredex.inventory.application.ports import PartReview
from wiredex.inventory.domain.errors import (
    IntakeRefusedError,
    InventoryError,
    PartAlreadyDefinedError,
    PartNotFoundError,
)
from wiredex.inventory.domain.intake import CellProblem, KnownPart, PartDraft, ProblemCode
from wiredex.inventory.domain.sheet import Column
from wiredex.inventory.domain.values import PartId, WorkspaceId
from wiredex.inventory.infrastructure.unit_of_work import SqlInventoryUnitOfWork
from wiredex.shared_kernel.application.ports import Clock, IdGenerator


class CatalogPartDesk:
    """The `PartCatalog` port over one `PartDrafts`, in inventory's words.

    A `PartDraft` goes in as a `RawPartDraft`, and a `DraftReview` comes back as a
    `PartReview`: each field becomes the column of its name, and each `DraftProblemKind` the
    `ProblemCode` of its name. Catalog's refusals leave as inventory's own errors, since the
    inventory router maps only those. Quick-add and an import review a draft before they
    define it, in this same transaction, so a refusal from `define` means another request
    changed the catalog in between.

    One desk per transaction, over one `PartDrafts`: its tree and schema caches then live
    exactly as long as one quick-add or one sheet (requirement 12.2).
    """

    def __init__(self, drafts: PartDrafts) -> None:
        self._drafts = drafts

    async def review(self, draft: PartDraft) -> PartReview:
        return _part_review(await self._drafts.review(_raw(draft)))

    async def define(self, draft: PartDraft, pinout_from: PartId | None = None) -> KnownPart:
        raw = _raw(draft)
        # Read first for the flag the new part is counted by: its category's, resolved along
        # the chain, which the part `PartDrafts` defines doesn't carry.
        review = await self._drafts.review(raw)
        source = None if pinout_from is None else PartDefinitionId(pinout_from)
        try:
            part = await self._drafts.define(raw, source)
        except DuplicateMpnError as error:
            raise await self._already_defined(raw, error) from error
        except CatalogError as error:
            raise _refusal(error) from error
        return _known(part, review)

    async def _already_defined(self, raw: RawPartDraft, error: DuplicateMpnError) -> InventoryError:
        """The 409 naming the part that holds the number, which catalog's error doesn't carry.

        Reviewing again in this transaction finds it. Should the holder have been deleted in
        between as well, there is no part to name, and the number is refused as it stands.
        """
        review = await self._drafts.review(raw)
        holder = review.existing
        if holder is None:
            return _refusal(error)
        # Quick-add's own sentence for the 409, whichever check found the holder first.
        message = f"{holder.mpn} is already the part {holder.name}"
        return PartAlreadyDefinedError(_known(holder, review), message)


class SqlIntakeUnitOfWork(SqlInventoryUnitOfWork):
    """Inventory's unit of work with the catalog bound to its session, as `IntakeUnitOfWork`.

    The base opens the session, begins, sets `app.workspace_id` for the transaction and binds
    inventory's repositories. The catalog's repositories then join that same session under
    the same workspace, so both of ADR 0007's gates cover catalog's rows and inventory's alike
    (requirement 10.1).
    """

    catalog: CatalogPartDesk

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        workspace_id: WorkspaceId,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        super().__init__(session_factory, workspace_id)
        self._clock = clock
        self._ids = ids

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        # Inventory's WorkspaceId and catalog's are the same UUID under two names, one per
        # module: neither module imports the other's domain.
        repositories = SqlCatalogRepositories(self.session, CatalogWorkspaceId(self._workspace))
        self.catalog = CatalogPartDesk(PartDrafts(repositories, self._clock, self._ids))
        return self


def _raw(draft: PartDraft) -> RawPartDraft:
    return RawPartDraft(
        category_id=None if draft.category_id is None else CategoryId(draft.category_id),
        category_path=draft.category_path,
        name=draft.name,
        manufacturer=draft.manufacturer,
        mpn=draft.mpn,
        package=draft.package,
        attributes=draft.attributes,
    )


def _part_review(review: DraftReview) -> PartReview:
    existing = review.existing
    return PartReview(
        problems=tuple(_cell_problem(problem) for problem in review.problems),
        existing=None if existing is None else _known(existing, review),
        category_id=None if review.category is None else review.category.id,
        category_path=review.category_path,
        tracked_individually=review.tracked_individually,
        identity=review.identity,
        not_stocked=review.not_stocked,
    )


def _cell_problem(problem: DraftProblem) -> CellProblem:
    """A draft's problem as a quick-add's or a row's: the field is the column of that name,
    and the row is left for the planner to stamp."""
    return CellProblem(None, problem.field, ProblemCode[problem.kind.name], problem.message)


def _known(part: PartDefinition, review: DraftReview) -> KnownPart:
    """The part with its category's flags, as the review resolved them. They are None only
    while a category is unknown, which a stored or just-defined part's never is."""
    return KnownPart(
        PartId(part.id),
        part.name.value,
        review.tracked_individually is True,
        review.not_stocked is True,
    )


def _refusal(error: CatalogError) -> InventoryError:
    """Catalog's refusal as inventory's: the draft's problems, a missing pinout source (a
    404, requirement 3.4), or a category or value the catalog stopped accepting since the
    review, which is a problem of the part as it stands."""
    message = str(error)
    match error:
        case DraftRefusedError():
            problems = tuple(_cell_problem(problem) for problem in error.problems)
            return IntakeRefusedError(problems, message)
        case SourceNotFoundError():
            return PartNotFoundError(message)
        case CategoryNotFoundError():
            problem = CellProblem(None, Column.CATEGORY, ProblemCode.UNKNOWN_CATEGORY, message)
            return IntakeRefusedError((problem,), message)
        case _:
            # A value the schema refuses now, or a number taken whose holder is gone again:
            # catalog's sentence names it, and the part as a whole is refused.
            problem = CellProblem(None, None, ProblemCode.INVALID, message)
            return IntakeRefusedError((problem,), message)
