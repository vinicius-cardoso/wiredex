"""Tables for the projects module, mapped imperatively onto the plain domain classes.

The third set of workspace-scoped tables, after catalog's and inventory's, so both carry a
`workspace_id` and their migration turns row-level security on for them (ADR 0007, design's
Data Models).

Things worth knowing when reading the DDL:

- A revision points at its project by the pair `(workspace_id, project_id)`, as `pins` points
  at `part_definitions`: Postgres checks foreign keys without row-level security, so a plain
  `project_id` key would let a bug file a revision of one workspace under another's project
  (requirement 8.4). The cascade is what makes deleting a project delete its revisions.
- `forked_from` is a plain key with `SET NULL`: deleting a fork's source keeps the fork and
  clears the pointer (requirement 5.4).
- The status CHECK lists all four ADR 0003 states though only `draft` is written, so
  10-build-lifecycle adds transitions, not a migration (decision 5).
- No relationships: the repositories flush a project before the revisions that point at it,
  as inventory's flush a lot before its movements.
"""

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Table,
    UniqueConstraint,
    Uuid,
    literal_column,
    text,
)

from wiredex.projects.domain.project import Project
from wiredex.projects.domain.revision import Revision
from wiredex.projects.domain.values import MAX_TAGS, RevisionStatus
from wiredex.projects.infrastructure.types import (
    DescriptionType,
    NotesType,
    ProjectNameType,
    RevisionLabelType,
    SummaryType,
    TagsType,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata

# Text with a CHECK constraint, never a Postgres enum type, as every enum column in the schema
# is: one more state would be a simple migration instead of an ALTER TYPE. Named `status`, so
# the naming convention calls the CHECK `ck_revisions_status`, as `units` has its own.
_revision_status = Enum(
    RevisionStatus,
    name="status",
    native_enum=False,
    create_constraint=True,
    values_callable=lambda members: [member.value for member in members],
    length=16,
)

projects = Table(
    "projects",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("name", ProjectNameType, nullable=False),
    Column("description", DescriptionType, nullable=True),
    # An array, not a table of tags: a project's tags are a short flat list read with the
    # project, and `tags @> ARRAY['esp32']` is the list's filter (decision 8).
    Column("tags", TagsType, nullable=False, server_default=text("'{}'::varchar[]")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    # Always true, since `id` alone is the key: it is here because a foreign key can only point
    # at a unique constraint, and the revisions' pair points at this one.
    UniqueConstraint("workspace_id", "id"),
    # The domain caps tags at twenty; the database repeats it.
    CheckConstraint(f"cardinality(tags) <= {MAX_TAGS}", name="at_most_twenty_tags"),
    Index("ix_projects_tags", "tags", postgresql_using="gin"),
)

revisions = Table(
    "revisions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("workspace_id", Uuid, nullable=False, index=True),
    Column("project_id", Uuid, nullable=False),
    Column("label", RevisionLabelType, nullable=False),
    Column("summary", SummaryType, nullable=True),
    Column("notes", NotesType, nullable=True),
    Column("status", _revision_status, nullable=False),
    # Indexed so the `SET NULL` a deleted source triggers doesn't scan the table.
    Column(
        "forked_from",
        Uuid,
        ForeignKey("revisions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    ForeignKeyConstraint(
        ["workspace_id", "project_id"],
        ["projects.workspace_id", "projects.id"],
        ondelete="CASCADE",
    ),
)

# Names and labels are unique folded: Weather station and weather station are one project, and
# A and a one revision (decisions 4 and 9). The expressions are named because the repositories
# fold through them too (`ProjectName.fold`, `RevisionLabel.fold`): written twice, they could
# drift apart and the query would stop using the index.
folded_name = literal_column("lower(name)", String)
folded_label = literal_column("lower(label)", String)

Index("uq_projects_name", projects.c.workspace_id, folded_name, unique=True)
# Leading with the project, it also serves reading a project's revisions and the cascade.
Index(
    "uq_revisions_label",
    revisions.c.workspace_id,
    revisions.c.project_id,
    folded_label,
    unique=True,
)

mapper_registry.map_imperatively(Project, projects)
mapper_registry.map_imperatively(Revision, revisions)
