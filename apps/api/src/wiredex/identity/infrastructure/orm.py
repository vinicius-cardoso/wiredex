"""Tables for the identity module, mapped imperatively onto the plain domain classes."""

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Table, Uuid
from sqlalchemy.orm import relationship

from wiredex.identity.domain.model import Membership, User, Workspace
from wiredex.identity.domain.session import Session
from wiredex.identity.domain.values import Role, WorkspaceKind
from wiredex.identity.infrastructure.types import (
    EmailType,
    NameType,
    PasswordHashType,
    SessionTokenHashType,
)
from wiredex.shared_kernel.infrastructure.orm import mapper_registry, metadata


def _enum(enum: type[Role] | type[WorkspaceKind], name: str) -> Enum:
    # Stored as text with a CHECK constraint: adding a value later is a simple migration.
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        length=16,
    )


users = Table(
    "users",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("email", EmailType, nullable=False, unique=True),
    Column("name", NameType, nullable=False),
    Column("password_hash", PasswordHashType, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True)),
)

workspaces = Table(
    "workspaces",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("name", NameType, nullable=False),
    Column("kind", _enum(WorkspaceKind, "workspace_kind"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

memberships = Table(
    "memberships",
    metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column(
        "workspace_id",
        Uuid,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
        index=True,
    ),
    Column("role", _enum(Role, "membership_role"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

sessions = Table(
    "sessions",
    metadata,
    Column("id", Uuid, primary_key=True),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("token_hash", SessionTokenHashType, nullable=False, unique=True),
    Column("device", String(120), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("last_seen_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

mapper_registry.map_imperatively(User, users)
mapper_registry.map_imperatively(Workspace, workspaces)
mapper_registry.map_imperatively(
    Membership,
    memberships,
    properties={
        # Never loaded (lazy="raise"): these only tell SQLAlchemy that a membership
        # depends on its user and workspace, so a single flush inserts those first.
        "_user": relationship(User, lazy="raise"),
        "_workspace": relationship(Workspace, lazy="raise"),
    },
)
mapper_registry.map_imperatively(
    Session,
    sessions,
    properties={"_user": relationship(User, lazy="raise")},  # insert order only
)
