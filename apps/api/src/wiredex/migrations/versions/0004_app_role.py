"""app role

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-24 12:00:00.000000

The API connects as `wiredex_app`, which can read and write rows but owns nothing and
isn't a superuser, so row-level security applies to it (ADR 0007). The role that runs
migrations keeps ownership. The role starts without a login: `wiredex db upgrade`
gives it one, with the password from WIREDEX_DATABASE_URL.
"""

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None

ROLE = "wiredex_app"
ROW_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"


def upgrade() -> None:
    # Roles belong to the whole server, not one database: it may exist already.
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{ROLE}') THEN
                CREATE ROLE {ROLE} NOLOGIN;
            END IF;
        END $$
    """)
    op.execute(f"ALTER ROLE {ROLE} NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {ROLE}")
    op.execute(f"GRANT {ROW_PRIVILEGES} ON ALL TABLES IN SCHEMA public TO {ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}")
    # Tables that later migrations create get the same grants.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT {ROW_PRIVILEGES} ON TABLES TO {ROLE}"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
    )
    # The schema version is the migrations' business only.
    op.execute(f"REVOKE ALL ON alembic_version FROM {ROLE}")


def downgrade() -> None:
    # Removes every grant and default privilege the role has in this database.
    op.execute(f"DROP OWNED BY {ROLE}")
    op.execute(f"DROP ROLE {ROLE}")
