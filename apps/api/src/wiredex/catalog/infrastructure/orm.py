"""Tables for the catalog module, mapped imperatively onto the plain domain classes.

These are the first tables of workspace data, so every one carries a `workspace_id` and its
migration turns row-level security on for it (ADR 0007, design §5).

`pins` is the exception to the "mapped imperatively" part: it is read and written with Core
only, because a pin has no identity outside its pinout.
"""

from enum import StrEnum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    func,
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship

from wiredex.catalog.domain.category import Category
from wiredex.catalog.domain.part import PartDefinition
from wiredex.catalog.domain.pinout import (
    MAX_PIN_FUNCTION_LENGTH,
    MAX_PIN_LABEL_LENGTH,
    MAX_PIN_NUMBER_LENGTH,
    PinType,
)
from wiredex.catalog.domain.schema import AttributeDefinition
from wiredex.catalog.domain.values import AttributeKind
from wiredex.catalog.infrastructure.types import (
    AttributeKeyType,
    AttributeLabelType,
    AttributeOptionsType,
    AttributeValuesType,
    CategoryNameType,
    ManufacturerType,
    MpnType,
    PackageType,
    PartNameType,
    UnitType,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata


def _enum(enum: type[StrEnum], name: str) -> Enum:
    # Text with a CHECK constraint, never a Postgres enum type: one more attribute kind or
    # pin type is then a simple migration instead of an ALTER TYPE.
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        length=16,
    )


categories = Table(
    "categories",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("parent_id", Uuid, ForeignKey("categories.id", ondelete="RESTRICT")),
    Column("name", CategoryNameType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # NULLS NOT DISTINCT, because a root category has no parent and Postgres would
    # otherwise take two roots named Passives for different rows (requirement 1.3).
    UniqueConstraint("workspace_id", "parent_id", "name", postgresql_nulls_not_distinct=True),
)

attribute_definitions = Table(
    "attribute_definitions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column(
        "category_id",
        Uuid,
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("key", AttributeKeyType, nullable=False),
    Column("label", AttributeLabelType, nullable=False),
    Column("kind", _enum(AttributeKind, "attribute_kind"), nullable=False),
    Column("unit", UnitType),
    Column("required", Boolean, nullable=False),
    Column("options", AttributeOptionsType, nullable=False, server_default=text("'[]'::jsonb")),
    Column("position", Integer, nullable=False),
    # Filled by Postgres and excluded from the mapping: the domain doesn't model it,
    # because nothing about a definition depends on when it was written (design §5).
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    # Only against the category's own definitions: an inherited key can't be shadowed
    # either, but that spans the ancestor chain, which no constraint can see (2.5, 2.6).
    UniqueConstraint("workspace_id", "category_id", "key"),
)

part_definitions = Table(
    "part_definitions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column(
        "category_id",
        Uuid,
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    Column("name", PartNameType, nullable=False),
    Column("manufacturer", ManufacturerType),
    Column("mpn", MpnType),
    Column("package", PackageType),
    Column("attributes", AttributeValuesType, nullable=False, server_default=text("'{}'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # Nothing needs a part to be unique by workspace and id — `id` alone is the primary key,
    # so this is always true and costs one index. It is here because a foreign key can only
    # point at a unique constraint, and `pins` points at this one (see below).
    UniqueConstraint("workspace_id", "id"),
    Index("ix_part_definitions_workspace_id_category_id", "workspace_id", "category_id"),
    # Nothing queries the attributes yet: the index is here because building it later
    # means building it over a full table, and it belongs with the column it serves.
    Index("ix_part_definitions_attributes", "attributes", postgresql_using="gin"),
)

# Requirement 4.6 as one partial unique index: TI/BME280 collides with ti/bme280, a
# missing manufacturer counts as the empty string so two parts can't share a bare MPN,
# and any number of parts without an MPN is fine. The two expressions are named because
# the repository's query folds through them too: written twice, they could drift apart
# and the query would stop using the index.
folded_manufacturer = literal_column("lower(coalesce(manufacturer, ''))", String)
folded_mpn = literal_column("lower(mpn)", String)

Index(
    "uq_part_definitions_mpn",
    part_definitions.c.workspace_id,
    folded_manufacturer,
    folded_mpn,
    unique=True,
    postgresql_where=text("mpn IS NOT NULL"),
)

# A part's pins, one row each, and the only catalog table with no imperative mapping: a pin
# has no identity outside its pinout and is never loaded alone, so `SqlPinouts` reads these
# rows into a `Pinout` and writes a `Pinout` back as rows, with Core (design §5). Rows rather
# than a JSONB column on the part, because the netlist will join to them and `functions`
# wants an index of its own.
pins = Table(
    "pins",
    metadata,
    Column("workspace_id", Uuid, nullable=False),
    Column("part_id", Uuid, nullable=False),
    # 0-based, the order the pinout was saved in: a pin table is read the way it was typed.
    Column("position", Integer, nullable=False),
    Column("number", String(MAX_PIN_NUMBER_LENGTH), nullable=False),
    Column("label", String(MAX_PIN_LABEL_LENGTH), nullable=False),
    Column("type", _enum(PinType, "pin_type"), nullable=False),
    # An array, not JSONB: a flat list of short strings, and `functions @> ARRAY['SDA']` is
    # what finding parts by function will ask.
    Column(
        "functions",
        ARRAY(String(MAX_PIN_FUNCTION_LENGTH)),
        nullable=False,
        server_default=text("'{}'::varchar[]"),
    ),
    # Volts, exact: numeric reaches `VoltageLevel`'s Decimal without a float rounding 3.3.
    Column("voltage", Numeric, nullable=True),
    # No surrogate id: a pin is identified by its part and its number, which is exactly how
    # the netlist's PinRef will reference it (ADR 0004).
    PrimaryKeyConstraint("part_id", "number"),
    UniqueConstraint("part_id", "position"),
    # ADR 0007's third gate. Postgres checks foreign keys without row-level security, so a
    # plain `part_id` key would let a bug file a pin of workspace A under a part of workspace
    # B; with the pair, the database itself refuses it (requirement 4.2). The cascade is what
    # makes deleting a part delete its pinout, so no repository has to remember to.
    ForeignKeyConstraint(
        ["workspace_id", "part_id"],
        ["part_definitions.workspace_id", "part_definitions.id"],
        ondelete="CASCADE",
    ),
    # Like the GIN index over attributes, ahead of the query that needs it: building it later
    # means building it over a full table.
    Index("ix_pins_functions", "functions", postgresql_using="gin"),
)

# The relationships are never loaded (lazy="raise"): they only tell SQLAlchemy that a
# definition and a part depend on their category, so one flush inserts the category first.
mapper_registry.map_imperatively(Category, categories)
mapper_registry.map_imperatively(
    AttributeDefinition,
    attribute_definitions,
    exclude_properties=["created_at"],
    properties={"_category": relationship(Category, lazy="raise")},
)
mapper_registry.map_imperatively(
    PartDefinition,
    part_definitions,
    properties={"_category": relationship(Category, lazy="raise")},
)
