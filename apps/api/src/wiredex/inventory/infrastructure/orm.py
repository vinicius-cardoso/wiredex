"""Tables for the inventory module, mapped imperatively onto the plain domain classes.

The second set of workspace-scoped tables (catalog's were the first), so every one carries a
`workspace_id` and its migration turns row-level security on for it (ADR 0007, design's Data
Models). `stock_balances` carries its own `workspace_id` for that reason, despite `lot_id`
being its key.

Two things are worth knowing when reading the DDL:

- `part_id` is a bare `uuid` with no foreign key to `part_definitions`: modules don't point
  at each other's tables (the rule `files` follows). A part's existence is checked through
  the `Parts` port, not a constraint.
- The `kind` CHECK lists all seven ADR 0002 names, not just the three v0.4.0 writes. The
  application is the gate on which three are written; the column stays open so v0.5.0 adds
  behaviour, not a migration ("expand now, contract later").
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.sql.expression import literal_column

from wiredex.inventory.domain.ledger import StockMovement
from wiredex.inventory.domain.location import Location
from wiredex.inventory.domain.lot import StockLot
from wiredex.inventory.domain.unit import Unit
from wiredex.inventory.domain.values import (
    MovementKind,
    MovementReason,
)
from wiredex.inventory.infrastructure.types import (
    LocationNameType,
    MacType,
    NoteType,
    QuantityType,
    SerialType,
    ShortCodeType,
    UnitStatusType,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata

# The six inventory tables, isolated by workspace in the migration.
ISOLATED = (
    "locations",
    "short_code_counters",
    "stock_lots",
    "stock_movements",
    "stock_balances",
    "units",
)

# Text with a CHECK constraint, never a Postgres enum type: one more movement kind or reason
# is then a simple migration instead of an ALTER TYPE. `MovementKind` lists all seven names,
# so the CHECK does too, and v0.5.0 grows into it without a migration.
_movement_kind = Enum(
    MovementKind,
    name="movement_kind",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
    length=16,
)
_movement_reason = Enum(
    MovementReason,
    name="movement_reason",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
    length=16,
)

locations = Table(
    "locations",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("parent_id", Uuid, ForeignKey("locations.id", ondelete="RESTRICT")),
    Column("code", ShortCodeType, nullable=False),
    Column("name", LocationNameType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # NULLS NOT DISTINCT, because a root location has no parent and Postgres would otherwise
    # take two roots named Lab for different rows (requirement 1.3, as catalog does). Named
    # by hand: both unique constraints start at `workspace_id`, so the naming convention
    # (`uq_%(table_name)s_%(column_0_name)s`) would give both the same name and they'd
    # collide. The explicit names keep them apart, and the migration uses these same names.
    UniqueConstraint(
        "workspace_id",
        "parent_id",
        "name",
        name="uq_locations_workspace_id_parent_id_name",
        postgresql_nulls_not_distinct=True,
    ),
    # The short code is unique per workspace and is what a scan or a search resolves.
    UniqueConstraint("workspace_id", "code", name="uq_locations_workspace_id_code"),
    # Trigram GIN index for the case-insensitive substring search over the code; needs the
    # `pg_trgm` extension the migration creates. `postgresql_ops` names the operator class so
    # `wiredex db check` sees it as present and reports no drift.
    Index(
        "ix_locations_code_trgm",
        "code",
        postgresql_using="gin",
        postgresql_ops={"code": "gin_trgm_ops"},
    ),
)

# The per-workspace short-code counter. A global Postgres SEQUENCE can't give gap-free,
# per-workspace numbers (it is per database and leaves gaps), so the counter is a row and
# `SqlShortCodes.next` bumps it inside the use case's transaction.
short_code_counters = Table(
    "short_code_counters",
    metadata,
    Column("workspace_id", Uuid, nullable=False),
    Column("kind", String(16), nullable=False),
    Column("next_value", Integer, nullable=False, server_default="1"),
    PrimaryKeyConstraint("workspace_id", "kind"),
    CheckConstraint("kind IN ('location', 'unit')", name="kind"),
)

stock_lots = Table(
    "stock_lots",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    # A bare uuid, no foreign key to part_definitions: modules don't point at each other's
    # tables. The part's existence is checked through the `Parts` port.
    Column("part_id", Uuid, nullable=False),
    Column("location_id", Uuid, ForeignKey("locations.id", ondelete="RESTRICT"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("workspace_id", "part_id", "location_id"),
    Index("ix_stock_lots_workspace_id_part_id", "workspace_id", "part_id"),
)

stock_movements = Table(
    "stock_movements",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("lot_id", Uuid, ForeignKey("stock_lots.id", ondelete="RESTRICT"), nullable=False),
    Column("kind", _movement_kind, nullable=False),
    # Signed: +receive, ±adjust delta, ∓ the two move rows. A plain int, not a Quantity: a
    # movement's change carries a sign, a lot's amount doesn't.
    Column("change", Integer, nullable=False),
    Column("reason", _movement_reason, nullable=True),
    Column("note", NoteType, nullable=True),
    Column("move_group", Uuid, nullable=True),
    # ADR 0002's "caused by": the four v0.5.0 kinds (RESERVE, RELEASE, CONSUME, RETURN) name a
    # revision, the other three don't, which the CHECK below holds. A bare uuid, no foreign key
    # into projects' tables (the module rule).
    Column("revision_id", Uuid, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # The four v0.5.0 kinds name a revision and the other three don't (requirement 8.1), and
    # each v0.5.0 kind has its sign (requirement 8.2). `StockMovement.__post_init__` refuses the
    # same rows, so a bug fails in a unit test rather than at the commit.
    CheckConstraint(
        "(kind IN ('RESERVE', 'RELEASE', 'CONSUME', 'RETURN')) = (revision_id IS NOT NULL)",
        name="revision_named",
    ),
    CheckConstraint(
        "(kind NOT IN ('RESERVE', 'RETURN') OR change > 0)"
        " AND (kind NOT IN ('RELEASE', 'CONSUME') OR change < 0)",
        name="revision_sign",
    ),
    # Rebuild reads a lot's rows in order.
    Index(
        "ix_stock_movements_workspace_id_lot_id_created_at",
        "workspace_id",
        "lot_id",
        "created_at",
    ),
    # Rebuild streams the workspace in order.
    Index("ix_stock_movements_workspace_id_created_at", "workspace_id", "created_at"),
    # A revision's holdings are folded from its rows: this partial index groups them by lot
    # (design's decision 1). Leads with `workspace_id`, which every query filters on.
    Index(
        "ix_stock_movements_revision",
        "workspace_id",
        "revision_id",
        postgresql_where=text("revision_id IS NOT NULL"),
    ),
)

stock_balances = Table(
    "stock_balances",
    metadata,
    Column("lot_id", Uuid, ForeignKey("stock_lots.id", ondelete="RESTRICT"), primary_key=True),
    # Its own workspace_id, despite lot_id being the key, so row-level security isolates it.
    Column("workspace_id", Uuid, nullable=False, index=True),
    # `on_hand` and `reserved` are `Quantity` on the domain balance, so they go through the
    # QuantityType decorator (as catalog does with every value-object column): reads
    # reconstruct a `Quantity`, writes serialize it. `available` stays a plain integer — it
    # is a derived property, excluded from the mapping and written by the repository.
    Column("on_hand", QuantityType, nullable=False),
    Column("reserved", QuantityType, nullable=False, server_default="0"),
    # A stored, checked column, not computed on read: the CHECK makes ADR 0002's invariant a
    # database guarantee as well as a domain one. It costs one integer per lot.
    Column("available", Integer, nullable=False),
    # Optimistic locking's column (ADR 0002); `BalanceSheet.put` bumps it and a stale write
    # is retried by the use case.
    Column("version", Integer, nullable=False, server_default="0"),
    CheckConstraint("on_hand >= 0", name="on_hand_non_negative"),
    CheckConstraint("reserved >= 0 AND reserved <= on_hand", name="reserved_within_on_hand"),
    CheckConstraint("available = on_hand - reserved", name="available_is_derived"),
)

units = Table(
    "units",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    # A bare uuid, no foreign key to part_definitions: modules don't point at each other's
    # tables. The part's existence is checked through the `Parts` port.
    Column("part_id", Uuid, nullable=False),
    # The unit's only location pointer: its location is its lot's location, so a unit and its
    # stock can never disagree about where it sits. RESTRICT keeps a lot with units from being
    # deleted out from under them (lots aren't deleted in v0.4.0 anyway).
    Column("lot_id", Uuid, ForeignKey("stock_lots.id", ondelete="RESTRICT"), nullable=False),
    Column("code", ShortCodeType, nullable=False),
    Column("serial", SerialType, nullable=True),
    Column("mac", MacType, nullable=True),
    Column("status", UnitStatusType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # The revision a held unit belongs to (design's decision 5): set exactly while the unit is
    # reserved or in use, cleared otherwise, which the CHECK below holds. A bare uuid, no
    # foreign key into projects' tables (the module rule).
    Column("revision_id", Uuid, nullable=True),
    # When it moved to the trash, None while it is live (16-soft-delete-and-trash, decision 1).
    Column("trashed_at", DateTime(timezone=True), nullable=True),
    # The code is unique per workspace and is what a scan or a search resolves.
    UniqueConstraint("workspace_id", "code", name="uq_units_workspace_id_code"),
    # A stray status can't be written; v0.5.0 widens the CHECK to the four values (design's
    # decision 5, the movement CHECK's pattern).
    CheckConstraint("status IN ('in_stock', 'reserved', 'in_use', 'retired')", name="status"),
    # `revision_id` is set exactly while the unit is reserved or in use.
    CheckConstraint(
        "(status IN ('reserved', 'in_use')) = (revision_id IS NOT NULL)", name="revision_held"
    ),
    Index("ix_units_workspace_id_part_id", "workspace_id", "part_id"),
    Index("ix_units_workspace_id_lot_id", "workspace_id", "lot_id"),
    # A revision's held units are read by revision (design's decision 5). Leads with
    # `workspace_id`, which every query filters on.
    Index(
        "ix_units_revision",
        "workspace_id",
        "revision_id",
        postgresql_where=text("revision_id IS NOT NULL"),
    ),
    # Trigram GIN indexes for the case-insensitive substring search over code, mac and serial;
    # need the `pg_trgm` extension the migration creates. `postgresql_ops` names the operator
    # class so `wiredex db check` sees it and reports no drift.
    Index(
        "ix_units_code_trgm",
        "code",
        postgresql_using="gin",
        postgresql_ops={"code": "gin_trgm_ops"},
    ),
    Index(
        "ix_units_mac_trgm",
        "mac",
        postgresql_using="gin",
        postgresql_ops={"mac": "gin_trgm_ops"},
    ),
    Index(
        "ix_units_serial_trgm",
        "serial",
        postgresql_using="gin",
        postgresql_ops={"serial": "gin_trgm_ops"},
    ),
)

# The trash, newest first, and only its records: a page of it reads in index order (16's
# decision 9). Partial, so the live rows, nearly all of them, cost it nothing.
Index(
    "ix_units_trashed",
    units.c.workspace_id,
    units.c.trashed_at.desc(),
    units.c.id.desc(),
    postgresql_where=text("trashed_at IS NOT NULL"),
)
# A serial is unique per (workspace, part), lower-cased, and only when present: two units of
# one part can't share a serial, two different parts may reuse one, and any number of units
# may have none — the mirror of catalog's partial MPN index. `lower(serial)` is written out
# because the repository's `serial_taken` folds through it too (Serial.fold()); written twice
# they could drift and the query would stop using the index.
folded_serial = literal_column("lower(serial)", String)

Index(
    "uq_units_workspace_id_part_id_serial",
    units.c.workspace_id,
    units.c.part_id,
    folded_serial,
    unique=True,
    postgresql_where=text("serial IS NOT NULL"),
)

# A MAC is unique per workspace, and only when present. A MAC is globally unique in reality,
# so no two units in a workspace share one whatever their parts. The stored value is already
# canonical (the `Mac` value object lower-cased it), so the index needs no lower().
Index(
    "uq_units_workspace_id_mac",
    units.c.workspace_id,
    units.c.mac,
    unique=True,
    postgresql_where=text("mac IS NOT NULL"),
)

# The mutable entities are mapped imperatively; the session writes and reads them. They
# carry no ORM relationships, so the repository flushes a lot before the movement that points
# at it (the foreign key's order isn't something the unit of work can infer on its own).
mapper_registry.map_imperatively(Location, locations)
mapper_registry.map_imperatively(StockLot, stock_lots)
mapper_registry.map_imperatively(StockMovement, stock_movements)
mapper_registry.map_imperatively(Unit, units)
# `StockBalance` is a frozen, slotted value object: it can't carry the mutable instance state
# an ORM mapping needs (SQLAlchemy can't weakref or instrument a slotted frozen class). So it
# is mapped by hand in `SqlBalanceSheet`, the way `Pinout` is in the catalog — the repository
# reads a row into a `StockBalance` and writes one back as columns, with `available` derived
# on the entity and written from its property so the `available = on_hand - reserved` CHECK
# holds. `stock_balances` stays a plain Core table here.
