"""Part drafts, reviewed and defined inside a transaction another module opened.

A draft is a part as a quick-add or a sheet row typed it: text no value object has read yet.
`review` says what the draft would do, name a stored part or define a new one, with every
problem it has at once; `define` writes it. Neither opens nor commits a unit of work: the
caller's transaction holds the part and its first stock together (design decision 2), the
shape `MoveStock.perform` already has inside `MoveUnit`.

One `PartDrafts` serves one transaction, so what it caches (the category tree and each
category's schema) lives exactly as long as one quick-add or one sheet (requirement 12.2).
"""

import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from wiredex.catalog.application.attributes import resolve_schema
from wiredex.catalog.application.categories import UNKNOWN_CATEGORY
from wiredex.catalog.application.parts import NewPart, define_part, load_part
from wiredex.catalog.application.ports import CatalogRepositories
from wiredex.catalog.domain.category import Category, CategoryFlags, CategoryPaths, flags_in_tree
from wiredex.catalog.domain.errors import (
    AmbiguousCategoryError,
    CatalogError,
    CategoryNotFoundError,
    DraftProblem,
    DraftProblemKind,
    DraftRefusedError,
    DuplicateMpnError,
    InvalidAttributeKeyError,
)
from wiredex.catalog.domain.part import PartDefinition, PartDetails
from wiredex.catalog.domain.pinout import Pinout
from wiredex.catalog.domain.schema import AttributeProblemKind, AttributeSchema
from wiredex.catalog.domain.values import (
    AttributeKey,
    AttributeKind,
    CategoryId,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
)
from wiredex.shared_kernel.application.ports import Clock, IdGenerator

_NOTHING: Mapping[str, object] = MappingProxyType({})


@dataclass(frozen=True, slots=True)
class RawPartDraft:
    """A part as a quick-add or a sheet row typed it; nothing is typed until `review`.

    A quick-add picks its category by id and a sheet row names one by path. Blank text is
    nothing given, as a blank cell is.
    """

    category_id: CategoryId | None = None
    category_path: str | None = None
    name: str | None = None
    manufacturer: str | None = None
    mpn: str | None = None
    package: str | None = None
    # By attribute key, blank cells already dropped. A yes-or-no value may arrive as text.
    attributes: Mapping[str, object] = field(default=_NOTHING)


@dataclass(frozen=True, slots=True)
class DraftReview:
    """What a draft would do, and what stands in its way.

    A draft naming a stored part has no problems: a row isn't judged on the cells it doesn't
    use (requirement 5.1). A new part's problems are every one of them (requirement 1.5).
    """

    problems: tuple[DraftProblem, ...]
    existing: PartDefinition | None  # the part already holding this manufacturer and MPN
    category: Category | None  # the draft's category, or the existing part's
    category_path: str | None  # its full path, for the preview
    tracked_individually: bool | None  # resolved along the chain
    identity: str | None  # manufacturer and MPN folded, what a sheet matches on
    # Resolved along the chain too, independently of tracking (09's decision 3); None while
    # the category is unknown, as tracking is.
    not_stocked: bool | None


class PartDrafts:
    """Part drafts reviewed and defined inside a transaction another module opened.

    Never opens or commits a unit of work: the caller's does (design decision 2).
    """

    def __init__(self, work: CatalogRepositories, clock: Clock, ids: IdGenerator) -> None:
        self._work = work
        self._clock = clock
        self._ids = ids
        self._tree: _Tree | None = None
        self._schemas: dict[CategoryId, AttributeSchema] = {}

    async def review(self, draft: RawPartDraft) -> DraftReview:
        return (await self._read(draft)).review

    async def define(
        self, draft: RawPartDraft, pinout_from: PartDefinitionId | None = None
    ) -> PartDefinition:
        """The draft as a new part, with a copy of `pinout_from`'s pins when it is given.

        Reviewed again rather than trusting the caller's review, and refused before anything
        is written: `DraftRefusedError` for a draft with problems, `DuplicateMpnError` for one
        naming a stored part, `PartNotFoundError` for a source the workspace doesn't hold
        (requirement 3.4). The caller commits.
        """
        new = _new_part(await self._read(draft))
        pinout = None if pinout_from is None else await self._pinout_of(pinout_from)
        part = await define_part(self._work, new, self._clock, self._ids)
        if pinout is not None:
            # The source's own value, so the copy is equal pin for pin and in order, and the
            # source is only read (requirements 3.2, 3.3).
            await self._work.pinouts.replace(part.id, pinout)
        return part

    async def _read(self, draft: RawPartDraft) -> _Reading:
        tree = await self._categories()
        typed = _Typed.of(draft, tree)
        existing = await self._stored(typed)
        if existing is not None:
            return _Reading(_review_of(tree, typed, (), existing))
        schema = await self._schema_of(typed.category.value)
        attributes = _with_switches_read(schema, typed.attributes)
        problems = (*typed.problems, *_attribute_problems(schema, attributes), *typed.bad_keys)
        part = None if problems else typed.new_part(attributes)
        return _Reading(_review_of(tree, typed, problems), part)

    async def _stored(self, typed: _Typed) -> PartDefinition | None:
        """The part holding the draft's manufacturer and MPN, folded as the index folds them."""
        naming = typed.naming
        if naming is None:
            return None
        return await self._work.parts.with_mpn(*naming)

    async def _categories(self) -> _Tree:
        # Once per instance: every path and flag a batch of drafts needs comes from one read.
        if self._tree is None:
            self._tree = _Tree(await self._work.categories.all())
        return self._tree

    async def _schema_of(self, category: Category | None) -> AttributeSchema | None:
        # Once per distinct category, however many drafts share it (requirement 12.2).
        if category is None:
            return None
        if category.id not in self._schemas:
            self._schemas[category.id] = await resolve_schema(self._work, category)
        return self._schemas[category.id]

    async def _pinout_of(self, part_id: PartDefinitionId) -> Pinout:
        source = await load_part(self._work, part_id)
        return await self._work.pinouts.of_part(source.id)


@dataclass(frozen=True, slots=True)
class _Cell[T]:
    """One field read through its value object: the value, or why it couldn't be read.

    Neither means the field was left blank, which a new part minds only for its category and
    its name.
    """

    value: T | None = None
    problem: DraftProblem | None = None


class _Tree:
    """The category tree read once: a category by id or by path, its path and its flags."""

    __slots__ = ("_by_id", "_paths")

    def __init__(self, categories: list[Category]) -> None:
        self._by_id = {category.id: category for category in categories}
        self._paths = CategoryPaths(categories)

    def get(self, category_id: CategoryId) -> Category | None:
        return self._by_id.get(category_id)

    def find(self, path: str) -> Category:
        return self._paths.find(path)

    def describe(self, category: Category | None) -> tuple[str | None, CategoryFlags | None]:
        """The category's full path and resolved flags, or neither while it is unknown."""
        if category is None:
            return None, None
        return self._paths.path_of(category), flags_in_tree(category, self._by_id)


@dataclass(frozen=True, slots=True)
class _Typed:
    """A draft's fields read through their value objects, before any schema is asked."""

    category: _Cell[Category]
    name: _Cell[PartName]
    manufacturer: _Cell[Manufacturer]
    mpn: _Cell[Mpn]
    package: _Cell[Package]
    attributes: Mapping[AttributeKey, object]
    bad_keys: tuple[DraftProblem, ...]  # attribute text that could never be a key

    @classmethod
    def of(cls, draft: RawPartDraft, tree: _Tree) -> _Typed:
        attributes, bad_keys = _keys(draft.attributes)
        return cls(
            _category(draft, tree),
            _name(draft.name),
            _detail(draft.manufacturer, Manufacturer, "manufacturer"),
            _detail(draft.mpn, Mpn, "mpn"),
            _detail(draft.package, Package, "package"),
            attributes,
            bad_keys,
        )

    @property
    def naming(self) -> tuple[Manufacturer | None, Mpn] | None:
        """The pair a stored part would hold, once both read; None without a part number.

        A missing manufacturer is part of the pair, as the unique index reads it: only a part
        stored without one matches it.
        """
        if self.mpn.value is None or self.manufacturer.problem is not None:
            return None
        return self.manufacturer.value, self.mpn.value

    @property
    def identity(self) -> str | None:
        naming = self.naming
        return None if naming is None else _identity(*naming)

    @property
    def problems(self) -> tuple[DraftProblem, ...]:
        """The fields' own problems, in the order the form shows the fields."""
        found = (
            self.category.problem,
            self.name.problem,
            self.manufacturer.problem,
            self.mpn.problem,
            self.package.problem,
        )
        return tuple(problem for problem in found if problem is not None)

    def new_part(self, attributes: Mapping[AttributeKey, object]) -> NewPart | None:
        """What `define` writes, or None while the category or the name is missing."""
        category, name = self.category.value, self.name.value
        if category is None or name is None:
            return None
        details = PartDetails(name, self.manufacturer.value, self.mpn.value, self.package.value)
        return NewPart(category.id, details, {key.value: raw for key, raw in attributes.items()})


@dataclass(frozen=True, slots=True)
class _Reading:
    review: DraftReview
    part: NewPart | None = None  # what `define` writes: a new part without a problem


def _review_of(
    tree: _Tree,
    typed: _Typed,
    problems: tuple[DraftProblem, ...],
    existing: PartDefinition | None = None,
) -> DraftReview:
    category = typed.category.value if existing is None else tree.get(existing.category_id)
    path, flags = tree.describe(category)
    return DraftReview(
        problems,
        existing,
        category,
        path,
        None if flags is None else flags.tracked_individually,
        typed.identity,
        None if flags is None else flags.not_stocked,
    )


def _new_part(reading: _Reading) -> NewPart:
    """The part `define` may write, or the refusal saying why it may not."""
    existing = reading.review.existing
    if existing is not None:
        # `define_part`'s own sentence, since this is the check it would make next.
        raise DuplicateMpnError(f"{existing.mpn} is already used by {existing.name}")
    if reading.part is None:
        raise DraftRefusedError(reading.review.problems)
    return reading.part


def _category(draft: RawPartDraft, tree: _Tree) -> _Cell[Category]:
    """The category a quick-add picked by id, or the one a sheet row names by path."""
    if draft.category_id is not None:
        found = tree.get(draft.category_id)
        if found is None:
            return _problem("category", DraftProblemKind.UNKNOWN_CATEGORY, UNKNOWN_CATEGORY)
        return _Cell(found)
    path = _given(draft.category_path)
    if path is None:
        return _problem("category", DraftProblemKind.MISSING, "a new part needs a category")
    return _by_path(tree, path)


def _by_path(tree: _Tree, path: str) -> _Cell[Category]:
    try:
        return _Cell(tree.find(path))
    except CategoryNotFoundError as error:
        return _problem("category", DraftProblemKind.UNKNOWN_CATEGORY, str(error))
    except AmbiguousCategoryError as error:
        return _problem("category", DraftProblemKind.AMBIGUOUS_CATEGORY, str(error))


def _name(text: str | None) -> _Cell[PartName]:
    if _given(text) is None:
        return _problem("name", DraftProblemKind.MISSING, "a new part needs a name")
    return _detail(text, PartName, "name")


def _detail[T](text: str | None, read: Callable[[str], T], about: str) -> _Cell[T]:
    """A field through its value object, whose sentence says what it refused."""
    given = _given(text)
    if given is None:
        return _Cell()
    try:
        return _Cell(read(given))
    except CatalogError as error:
        return _problem(about, DraftProblemKind.INVALID, str(error))


def _given(text: str | None) -> str | None:
    """The text, or None when it is blank: a blank field or cell is nothing given."""
    return None if text is None or not text.strip() else text


def _problem[T](about: str, kind: DraftProblemKind, message: str) -> _Cell[T]:
    return _Cell(problem=DraftProblem(about, kind, message))


def _keys(
    raw: Mapping[str, object],
) -> tuple[dict[AttributeKey, object], tuple[DraftProblem, ...]]:
    """The attribute map by key, and a problem for each text that could never be a key."""
    keys: dict[AttributeKey, object] = {}
    bad: list[DraftProblem] = []
    for text, value in raw.items():
        try:
            keys[AttributeKey(text)] = value
        except InvalidAttributeKeyError:
            # `check`'s sentence for a key the schema doesn't define, which this can't be.
            message = f"{text!r} is not an attribute of this category"
            bad.append(DraftProblem(text, DraftProblemKind.NOT_AN_ATTRIBUTE, message))
    return keys, tuple(bad)


# How a sheet spells a yes-or-no value, in either language, compared case-folded (5.9).
_YES = frozenset({"true", "yes", "sim", "1"})
_NO = frozenset({"false", "no", "não", "0"})


def _with_switches_read(
    schema: AttributeSchema | None, values: Mapping[AttributeKey, object]
) -> dict[AttributeKey, object]:
    """Each yes-or-no attribute given as text read as the boolean `BoolValidator` takes.

    A sheet can only hold text, and the part form sends a real boolean. Text that is neither
    spelling stays text, so the validator refuses it as the value it is.
    """
    if schema is None:
        return dict(values)
    return {key: _switch(schema, key, raw) for key, raw in values.items()}


def _switch(schema: AttributeSchema, key: AttributeKey, raw: object) -> object:
    definition = schema.get(key)
    if definition is None or definition.kind is not AttributeKind.BOOL or not isinstance(raw, str):
        return raw
    # NFC first, so a não typed with a combining tilde reads as the one spelled here.
    word = unicodedata.normalize("NFC", raw).strip().casefold()
    if word in _YES:
        return True
    return False if word in _NO else raw


# What `check` found, in a draft's words: a required value left out is missing, and any value
# its validator refuses is invalid, whatever the attribute's kind.
_KINDS: Mapping[AttributeProblemKind, DraftProblemKind] = {
    AttributeProblemKind.MISSING_REQUIRED: DraftProblemKind.MISSING,
    AttributeProblemKind.WRONG_KIND: DraftProblemKind.INVALID,
    AttributeProblemKind.NOT_IN_OPTIONS: DraftProblemKind.INVALID,
    AttributeProblemKind.UNKNOWN_KEY: DraftProblemKind.NOT_AN_ATTRIBUTE,
}


def _attribute_problems(
    schema: AttributeSchema | None, values: Mapping[AttributeKey, object]
) -> tuple[DraftProblem, ...]:
    """Every value the schema refuses; nothing to ask while the category is a problem."""
    if schema is None:
        return ()
    return tuple(
        DraftProblem(problem.key.value, _KINDS[problem.problem], problem.message)
        for problem in schema.check(values)
    )


# Between the folded manufacturer and part number. Both value objects collapse whitespace to
# single spaces, so neither holds a line break and a pair can never be read two ways.
_IDENTITY_SEPARATOR = "\n"


def _identity(manufacturer: Manufacturer | None, mpn: Mpn) -> str:
    """The pair as the partial unique index folds it: a missing manufacturer is empty text."""
    folded = "" if manufacturer is None else manufacturer.value.lower()
    return f"{folded}{_IDENTITY_SEPARATOR}{mpn.fold()}"
