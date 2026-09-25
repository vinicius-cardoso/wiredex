"""A category's fields: resolved along the tree, and a part measured against them.

Two directions, deliberately different. `validate` is the write path and refuses whatever
doesn't fit, so a part is never stored half-valid. `review` is the read path and refuses
nothing: it lists what no longer fits, because fixing a schema late must not cost the owner
data already typed (design §2.5).
"""

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from wiredex.catalog.domain.errors import (
    CatalogError,
    DuplicateAttributeKeyError,
    InvalidAttributeKeyError,
    InvalidAttributeOptionsError,
)
from wiredex.catalog.domain.validators import VALIDATORS
from wiredex.catalog.domain.values import (
    AttributeDefinitionId,
    AttributeKey,
    AttributeKind,
    AttributeLabel,
    CategoryId,
    Unit,
)


@dataclass(eq=False)
class AttributeDefinition:
    """One field the parts of a category have: what it's called, what it takes, if it's needed.

    Mutable and compared by identity, as the other entities are. `label`, `required`,
    `options` and `position` are editable; `key` and `kind` are not, because changing either
    makes it a different attribute wearing the same name (design §6).
    """

    id: AttributeDefinitionId
    category_id: CategoryId
    key: AttributeKey
    label: AttributeLabel
    kind: AttributeKind
    unit: Unit | None = None
    required: bool = False
    options: tuple[str, ...] = ()
    position: int = 0

    def __post_init__(self) -> None:
        # Here rather than in the use case: an enum with nothing to choose from is not a
        # definition the domain can validate against, so no path may build one.
        self.check_options(self.options)

    def check_options(self, options: tuple[str, ...]) -> None:
        """The options rule, also for an edit that replaces them (requirement 2.3)."""
        if self.kind is AttributeKind.ENUM and not options:
            raise InvalidAttributeOptionsError(f"{self.key} is a choice, so it needs some options")
        if self.kind is not AttributeKind.ENUM and options:
            raise InvalidAttributeOptionsError(f"{self.key} is a {self.kind}, so it has no options")


_NO_VALUES: Mapping[AttributeKey, object] = MappingProxyType({})


class AttributeValues(Mapping[AttributeKey, object]):
    """The values one part stores, already coerced. Immutable: revising a part builds a new one."""

    __slots__ = ("_values",)

    def __init__(self, values: Mapping[AttributeKey, object] = _NO_VALUES) -> None:
        # A copy, so nobody edits a part's attributes through the dict they passed in.
        self._values: dict[AttributeKey, object] = dict(values)

    def __getitem__(self, key: AttributeKey) -> object:
        return self._values[key]

    def __iter__(self) -> Iterator[AttributeKey]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __repr__(self) -> str:
        return f"AttributeValues({self._values!r})"


class AttributeProblemKind(StrEnum):
    """Why one attribute of a part no longer fits its schema — requirement 5.3's four."""

    MISSING_REQUIRED = "missing_required"
    WRONG_KIND = "wrong_kind"
    NOT_IN_OPTIONS = "not_in_options"
    UNKNOWN_KEY = "unknown_key"


@dataclass(frozen=True, slots=True)
class AttributeProblem:
    """One attribute that doesn't fit: which key, why, and a sentence the web can show."""

    key: AttributeKey
    problem: AttributeProblemKind
    message: str


class AttributeSchema:
    """A category's own definitions plus every one inherited from its ancestors, in form order.

    Built by the application, which is what can read the tree; the schema itself only knows
    that a key resolves to exactly one definition.
    """

    __slots__ = ("_by_key", "_definitions")

    def __init__(self, definitions: Iterable[AttributeDefinition]) -> None:
        self._definitions = tuple(definitions)
        self._by_key: dict[AttributeKey, AttributeDefinition] = {}
        for definition in self._definitions:
            if definition.key in self._by_key:
                raise DuplicateAttributeKeyError(
                    f"{definition.key} is already defined: an inherited key can't be shadowed"
                )
            self._by_key[definition.key] = definition

    @classmethod
    def inherited(cls, chain: Sequence[Iterable[AttributeDefinition]]) -> AttributeSchema:
        """Resolves one group per category, the root's first and the category's own last.

        Inheritance is additive and a child may not shadow an inherited key, so a key seen
        twice is a `DuplicateAttributeKeyError`: "which definition applies" has one answer
        (requirement 2.6). Within a category, `position` orders the fields (requirement 2.7).
        """
        return cls(definition for group in chain for definition in sorted(group, key=_form_order))

    def __iter__(self) -> Iterator[AttributeDefinition]:
        return iter(self._definitions)

    def __len__(self) -> int:
        return len(self._definitions)

    def __contains__(self, key: AttributeKey) -> bool:
        return key in self._by_key

    def get(self, key: AttributeKey) -> AttributeDefinition | None:
        return self._by_key.get(key)

    def validate(self, values: Mapping[str, object]) -> AttributeValues:
        """The whole map as the catalog stores it, or a refusal naming the attribute that failed.

        Whole map at a time on purpose: a part is validated as one thing, so it can never be
        saved half-valid (requirement 4.8).
        """
        given = self._resolve_keys(values)
        validated: dict[AttributeKey, object] = {}
        for definition in self._definitions:
            # A null is nothing sent: clearing an optional field and omitting it are the same.
            raw = given.get(definition.key)
            if raw is None:
                if definition.required:
                    raise CatalogError(f"{definition.key} is required")
                continue
            validated[definition.key] = VALIDATORS[definition.kind].coerce(definition, raw)
        return AttributeValues(validated)

    def review(self, values: AttributeValues) -> tuple[AttributeProblem, ...]:
        """What no longer fits, one problem per attribute. Never raises: a part stays readable.

        A schema edit leaves stored values untouched, so fit is a question answered on read
        (requirement 5.2). Definitions come first, in form order, then the keys nothing
        defines any more.
        """
        problems = [
            problem
            for definition in self._definitions
            if (problem := _review(definition, values)) is not None
        ]
        problems.extend(
            AttributeProblem(
                key, AttributeProblemKind.UNKNOWN_KEY, f"{key} is not defined any more"
            )
            for key in values
            if key not in self._by_key
        )
        return tuple(problems)

    def _resolve_keys(self, values: Mapping[str, object]) -> dict[AttributeKey, object]:
        """Client keys as domain keys, refusing one the schema doesn't define (requirement 4.3)."""
        resolved: dict[AttributeKey, object] = {}
        for raw_key, raw in values.items():
            key = _read_key(raw_key)
            # Named as typed, because an unknown key is usually a typo of a defined one, and
            # reading "resistence" back is what makes that obvious.
            if key is None or key not in self._by_key:
                raise CatalogError(f"{raw_key!r} is not an attribute of this category")
            resolved[key] = raw
        return resolved


def _review(definition: AttributeDefinition, values: AttributeValues) -> AttributeProblem | None:
    if definition.key not in values:
        if definition.required:
            return AttributeProblem(
                definition.key,
                AttributeProblemKind.MISSING_REQUIRED,
                f"{definition.key} is required",
            )
        return None
    try:
        VALIDATORS[definition.kind].coerce(definition, values[definition.key])
    except CatalogError as error:
        return AttributeProblem(definition.key, _problem_of(definition.kind), str(error))
    return None


def _problem_of(kind: AttributeKind) -> AttributeProblemKind:
    # Whatever an enum refuses is a value that is not among its options, its type included.
    if kind is AttributeKind.ENUM:
        return AttributeProblemKind.NOT_IN_OPTIONS
    return AttributeProblemKind.WRONG_KIND


def _read_key(text: str) -> AttributeKey | None:
    """The key as the domain spells it, or None when the text could never be one."""
    try:
        return AttributeKey(text)
    except InvalidAttributeKeyError:
        return None


def _form_order(definition: AttributeDefinition) -> tuple[int, str]:
    # The key breaks ties, so two definitions sharing a position still come out in one order.
    return definition.position, definition.key.value
