"""A kind of part, described once: what it is called, how it is catalogued, what it measures.

Attribute values arrive already coerced, because only the application can read the category's
resolved schema. What the entity owns is the other half: what changed, and when.
"""

from dataclasses import dataclass
from datetime import datetime

from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.schema import AttributeValues
from wiredex.catalog.domain.values import (
    CategoryId,
    Manufacturer,
    Mpn,
    Package,
    PartDefinitionId,
    PartName,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class PartDetails:
    """Everything editable about a part that isn't an attribute value or its category.

    One object, so defining and revising take the same fields: a part is named and
    catalogued as one thing, and comparing it is how `revise` knows nothing changed.
    """

    name: PartName
    manufacturer: Manufacturer | None = None
    mpn: Mpn | None = None
    package: Package | None = None


@dataclass(eq=False)
class PartDefinition:
    """A resistor, not *this* resistor: stock, BOMs and wiring point at one of these (ADR 0005)."""

    id: PartDefinitionId
    workspace_id: WorkspaceId
    category_id: CategoryId
    name: PartName
    attributes: AttributeValues
    manufacturer: Manufacturer | None
    mpn: Mpn | None
    package: Package | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def define(
        cls,
        part_id: PartDefinitionId,
        category: Category,
        details: PartDetails,
        attributes: AttributeValues,
        now: datetime,
    ) -> PartDefinition:
        """A new part, created and last updated at the same instant.

        The category rather than its id: the use case has already loaded it to resolve the
        schema, and taking the workspace from it is what keeps a part from ever landing in
        one workspace under a category of another.
        """
        return cls(
            id=part_id,
            workspace_id=category.workspace_id,
            category_id=category.id,
            name=details.name,
            attributes=attributes,
            manufacturer=details.manufacturer,
            mpn=details.mpn,
            package=details.package,
            created_at=now,
            updated_at=now,
        )

    @property
    def details(self) -> PartDetails:
        """What the part is called and how it is catalogued, as one comparable value."""
        return PartDetails(self.name, self.manufacturer, self.mpn, self.package)

    def revise(self, details: PartDetails, attributes: AttributeValues, now: datetime) -> bool:
        """Replaces the details and the whole attribute map (requirement 4.8).

        The whole map, never a merge, so a part that needed review is saved only once every
        value fits. Returns whether anything changed, so an update that changes nothing
        commits nothing (requirement 4.9).
        """
        if self.details == details and self.attributes == attributes:
            return False
        self.name = details.name
        self.manufacturer = details.manufacturer
        self.mpn = details.mpn
        self.package = details.package
        self.attributes = attributes
        self.updated_at = now
        return True

    def pinout_changed(self, now: datetime) -> None:
        """The part's pins were replaced, which counts as the part changing (requirement 1.5).

        The pins are rows of their own table and the part row holds none of them, so there is
        nothing else to write here. The timestamp is still the part's, and a part's timestamp
        only ever moves through the part, as `revise` does.
        """
        self.updated_at = now

    def reclassify(
        self, category_id: CategoryId, attributes: AttributeValues, now: datetime
    ) -> None:
        """Moves the part to another category, with the values that category's schema accepted.

        The new map comes in because the use case has validated it against the new schema and
        refused the move if it didn't fit (requirement 4.10): the same values can be valid
        under one category and wrong under another. The workspace never changes, so this
        takes the id and not the category.
        """
        self.category_id = category_id
        self.attributes = attributes
        self.updated_at = now
