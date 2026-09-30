"""Tables for the firmware module, mapped imperatively onto the plain domain classes.

Four workspace-scoped tables, so each carries a `workspace_id` and its migration turns row-level
security on for it (ADR 0007, design's Data Models).

Things worth knowing when reading the DDL:

- Every row points at its parent by a pair that starts with `workspace_id`, as projects' rows
  do: Postgres checks foreign keys without row-level security, so a plain `firmware_id` or
  `version_id` key would let a bug file a version of one workspace under another's firmware
  (requirement 9.4). The cascades are what make deleting a firmware delete its versions, their
  files and its links, and deleting a version delete its files (requirements 1.9, 8.1).
- A link names projects' revision by a bare id, with no foreign key (decision 2): modules don't
  point at each other's tables, and a link outlives its revision (decision 3).
- `based_on` is a plain key with `SET NULL`, as `revisions.forked_from` is: deleting a base
  keeps the versions started from it and clears the pointer (requirement 8.2).
- `released_dated` ties a release's date to its status, and `size_is_length` a file's stored
  size to its text, so the sum a version's limit reads without the text can't drift from it
  (decision 9).
- No relationships: `add` flushes a firmware before its links and a version before its files,
  which are Core rows (09's lines and 11's nets are too), with no identity worth an ORM object.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    literal_column,
)

from wiredex.firmware.domain.firmware import Firmware
from wiredex.firmware.domain.values import Framework
from wiredex.firmware.domain.version import FirmwareVersion, VersionStatus
from wiredex.firmware.infrastructure.types import (
    BoardTargetType,
    ChangelogType,
    DescriptionType,
    FirmwareNameType,
    SemVerType,
    SourcePathType,
    SourceTextType,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata

# Text with a CHECK constraint, never a Postgres enum type, as every enum column in the schema
# is: a sixth framework or a third status is a CHECK and a union, not an ALTER TYPE (decision
# 11). Named after their columns, so the naming convention calls the CHECKs
# `ck_firmware_framework` and `ck_firmware_versions_status`.
_framework = Enum(
    Framework,
    name="framework",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
    length=16,
)
_version_status = Enum(
    VersionStatus,
    name="status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
    length=16,
)

# `firmware_table` in code: `firmware` is the table's name, a mass noun (decision 1), and what
# every use case calls one firmware.
firmware_table = Table(
    "firmware",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("name", FirmwareNameType, nullable=False),
    Column("target", BoardTargetType, nullable=False),
    Column("framework", _framework, nullable=False),
    Column("description", DescriptionType, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # Its last change, which orders the list (requirement 2.2).
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # Always true, since `id` alone is the key: what the links' and versions' pairs point at.
    UniqueConstraint("workspace_id", "id"),
)

firmware_revisions = Table(
    "firmware_revisions",
    metadata,
    Column("workspace_id", Uuid, nullable=False),
    Column("firmware_id", Uuid, nullable=False),
    # Projects' revision, by id alone (decision 2).
    Column("revision_id", Uuid, nullable=False),
    # When it was linked: the order a firmware's revisions are named in (requirement 3.5).
    Column("created_at", DateTime(timezone=True), nullable=False),
    # A firmware runs on a revision once, so a repeated link finds its row (requirement 3.1).
    PrimaryKeyConstraint("workspace_id", "firmware_id", "revision_id"),
    ForeignKeyConstraint(
        ["workspace_id", "firmware_id"],
        ["firmware.workspace_id", "firmware.id"],
        ondelete="CASCADE",
    ),
    # A revision's firmware (requirement 3.4) and a fork's copy (decision 4) look up by it.
    Index("ix_firmware_revisions_revision", "workspace_id", "revision_id"),
)

firmware_versions = Table(
    "firmware_versions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False),
    Column("firmware_id", Uuid, nullable=False),
    # The canonical text, `FirmwareVersion.number` in the domain.
    Column("version", SemVerType, nullable=False),
    Column("changelog", ChangelogType, nullable=True),
    Column("status", _version_status, nullable=False),
    # Indexed so the `SET NULL` a deleted base triggers doesn't scan the table, as
    # `revisions.forked_from` is.
    Column(
        "based_on",
        Uuid,
        ForeignKey("firmware_versions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("released_at", DateTime(timezone=True), nullable=True),
    # A release is dated, and only a release (requirement 6.1).
    CheckConstraint("(status = 'released') = (released_at IS NOT NULL)", name="released_dated"),
    # Always true, as the firmware's pair is: what the source files' pair points at.
    UniqueConstraint("workspace_id", "id"),
    ForeignKeyConstraint(
        ["workspace_id", "firmware_id"],
        ["firmware.workspace_id", "firmware.id"],
        ondelete="CASCADE",
    ),
)

source_files = Table(
    "source_files",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False),
    Column("version_id", Uuid, nullable=False),
    Column("path", SourcePathType, nullable=False),
    Column("content", SourceTextType, nullable=False),
    # The text's bytes of UTF-8, stored so a version's total is one sum that never reads the
    # text (decision 9).
    Column("size", Integer, nullable=False),
    CheckConstraint("size = octet_length(content)", name="size_is_length"),
    ForeignKeyConstraint(
        ["workspace_id", "version_id"],
        ["firmware_versions.workspace_id", "firmware_versions.id"],
        ondelete="CASCADE",
    ),
)

# Names and paths are unique folded: Weather station and weather station are one firmware, and
# Config.h and config.h one file to Windows and macOS (requirements 1.3, 7.3). The name's
# expression is named because `SqlFirmwares.named` folds through it too (`FirmwareName.fold`):
# written twice, they could drift apart and the query would stop using the index.
folded_name = literal_column("lower(name)", String)

Index("uq_firmware_name", firmware_table.c.workspace_id, folded_name, unique=True)
# `SemVer` stores its number lower-cased, so the column needs no folding (decision 6). Leading
# with the firmware, it also serves reading a firmware's versions and the cascade.
Index(
    "uq_firmware_versions_version",
    firmware_versions.c.workspace_id,
    firmware_versions.c.firmware_id,
    firmware_versions.c.version,
    unique=True,
)
# Leading with the version, it also serves reading a version's files and the cascade.
Index(
    "uq_source_files_path",
    source_files.c.workspace_id,
    source_files.c.version_id,
    literal_column("lower(path)", String),
    unique=True,
)

mapper_registry.map_imperatively(Firmware, firmware_table)
# The column is `version`, the entity's attribute `number`: `version.number` reads plainly
# where `version.version` wouldn't.
mapper_registry.map_imperatively(
    FirmwareVersion, firmware_versions, properties={"number": firmware_versions.c.version}
)
