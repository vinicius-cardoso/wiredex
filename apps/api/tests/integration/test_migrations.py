import asyncio
from uuid import uuid7

import pytest
from alembic import command
from click.testing import CliRunner
from sqlalchemy import make_url, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.migrations import APP_ROLE, AppLogin, alembic_config, let_app_role_log_in

pytestmark = pytest.mark.integration


def test_migrations_upgrade_downgrade_and_upgrade_again(database_url: str) -> None:
    config = alembic_config(database_url)

    command.upgrade(config, "head")
    command.downgrade(config, "base")
    command.upgrade(config, "head")


def test_models_and_migrations_agree(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "head")

    # Raises if autogenerate would produce operations: a model change without a migration.
    command.check(config)


def test_the_upgrade_command_lets_the_api_log_in_as_the_app_role(database_url: str) -> None:
    app_url = make_url(database_url).set(username=APP_ROLE, password="fresh:password'%")
    app_url_text = app_url.render_as_string(hide_password=False)

    result = CliRunner().invoke(
        cli,
        ["db", "upgrade"],
        env={"WIREDEX_ADMIN_DATABASE_URL": database_url, "WIREDEX_DATABASE_URL": app_url_text},
    )

    assert result.exit_code == 0, result.output
    assert asyncio.run(_current_user(app_url_text)) == APP_ROLE


def test_0008_leaves_the_trigram_indexes_and_keeps_the_extension_on_downgrade(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    trigram_indexes = {
        "ix_part_definitions_name_trgm",
        "ix_part_definitions_mpn_trgm",
        "ix_part_definitions_manufacturer_trgm",
    }

    command.upgrade(config, "0008")
    try:
        assert asyncio.run(_indexes_on(database_url, "part_definitions")) >= trigram_indexes
        assert asyncio.run(_has_extension(database_url, "pg_trgm"))

        command.downgrade(config, "0007")
        # The indexes go; the extension stays, as the migration's downgrade documents.
        assert not (asyncio.run(_indexes_on(database_url, "part_definitions")) & trigram_indexes)
        assert asyncio.run(_has_extension(database_url, "pg_trgm"))
    finally:
        command.upgrade(config, "head")


def test_0024_widens_the_attachment_checks_for_builds_and_narrows_them_back(
    database_url: str,
) -> None:
    # 20-firmware-builds: a version is a subject and a build a kind from 0024 on, and neither
    # before it.
    config = alembic_config(database_url)
    try:
        command.upgrade(config, "0024")
        wide = asyncio.run(_attachment_checks(database_url))
        assert "firmware_version" in wide["ck_attachments_subject_kind"]
        assert "firmware_build" in wide["ck_attachments_attachment_kind"]

        command.downgrade(config, "0023")
        narrow = asyncio.run(_attachment_checks(database_url))
        assert "firmware_version" not in narrow["ck_attachments_subject_kind"]
        assert "firmware_build" not in narrow["ck_attachments_attachment_kind"]
        assert "revision" in narrow["ck_attachments_subject_kind"]
        assert "gerbers" in narrow["ck_attachments_attachment_kind"]
    finally:
        command.upgrade(config, "head")


async def _attachment_checks(database_url: str) -> dict[str, str]:
    """Each CHECK on `attachments` by name, as Postgres writes its condition."""
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
                    " WHERE conrelid = 'attachments'::regclass AND contype = 'c'"
                )
            )
            return dict(rows.tuples().all())
    finally:
        await engine.dispose()


def test_the_app_login_waits_for_the_migration_that_creates_the_role(database_url: str) -> None:
    config = alembic_config(database_url)
    command.downgrade(config, "0003")
    try:
        granted = asyncio.run(let_app_role_log_in(database_url, AppLogin("unused")))
    finally:
        command.upgrade(config, "head")

    assert granted is False


async def _current_user(database_url: str) -> str | None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            user: str | None = await connection.scalar(text("SELECT current_user"))
            return user
    finally:
        await engine.dispose()


async def _indexes_on(database_url: str, table: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            rows = await connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE tablename = :table"),
                {"table": table},
            )
            return {name for (name,) in rows}
    finally:
        await engine.dispose()


async def _has_extension(database_url: str, name: str) -> bool:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            found = await connection.scalar(
                text("SELECT 1 FROM pg_extension WHERE extname = :name"), {"name": name}
            )
            return found is not None
    finally:
        await engine.dispose()


# --- 0018: the build lifecycle's schema (spec 10, design's decision 6) --------------------

# A minimal seeded graph, inserted as the owner (which row-level security doesn't apply to, as
# migrations aren't): one location, one lot, and the rows each test needs under it. `units` and
# `stock_movements` point at the lot; nothing here points at projects' tables, since both
# `revision_id` columns are bare uuids.
_WORKSPACE = "0199f2a4-0000-7000-8000-000000000001"
_LOCATION = "0199f2a4-0000-7000-8000-000000000002"
_LOT = "0199f2a4-0000-7000-8000-000000000003"
_PART = "0199f2a4-0000-7000-8000-000000000004"
_REVISION = "0199f2a4-0000-7000-8000-000000000005"


async def _seed_lot(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            "INSERT INTO locations (id, workspace_id, parent_id, code, name, created_at)"
            " VALUES (:id, :ws, NULL, 'WX-L-0001', 'Lab', now())"
        ),
        {"id": _LOCATION, "ws": _WORKSPACE},
    )
    await connection.execute(
        text(
            "INSERT INTO stock_lots (id, workspace_id, part_id, location_id, created_at)"
            " VALUES (:id, :ws, :part, :loc, now())"
        ),
        {"id": _LOT, "ws": _WORKSPACE, "part": _PART, "loc": _LOCATION},
    )


async def _insert_unit(
    connection: AsyncConnection, *, status: str, revision_id: str | None
) -> None:
    await connection.execute(
        text(
            "INSERT INTO units (id, workspace_id, part_id, lot_id, code, serial, mac, status,"
            " created_at, revision_id)"
            " VALUES (:id, :ws, :part, :lot, :code, NULL, NULL, :status, now(), :rev)"
        ),
        {
            "id": str(uuid7()),
            "ws": _WORKSPACE,
            "part": _PART,
            "lot": _LOT,
            "code": f"WX-U-{uuid7().int % 10000:04d}",
            "status": status,
            "rev": revision_id,
        },
    )


async def _insert_movement(
    connection: AsyncConnection, *, kind: str, change: int, revision_id: str | None
) -> None:
    await connection.execute(
        text(
            "INSERT INTO stock_movements (id, workspace_id, lot_id, kind, change, reason, note,"
            " move_group, revision_id, created_at)"
            " VALUES (:id, :ws, :lot, :kind, :change, NULL, NULL, NULL, :rev, now())"
        ),
        {
            "id": str(uuid7()),
            "ws": _WORKSPACE,
            "lot": _LOT,
            "kind": kind,
            "change": change,
            "rev": revision_id,
        },
    )


def test_0018_downgrade_returns_held_units_and_keeps_the_new_movement_kinds(
    database_url: str,
) -> None:
    # A reserved unit, an in-use one, and the RESERVE and CONSUME movements naming their
    # revision. The downgrade turns the reserved unit back to in_stock and the in-use one to
    # retired, clearing both links, so the old two-value CHECK holds; it deletes no movement,
    # so the new kinds stay in the ledger (design's decision 6). Then up again is clean.
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    asyncio.run(_seed_held_stock(database_url))

    command.downgrade(config, "0017")

    # After the downgrade the `revision_id` column is gone, so only the status can be read: the
    # reserved unit is back in_stock and the in-use one retired, which the old two-value CHECK
    # allows. The movements outlive the downgrade, the new kinds still in the ledger.
    statuses, movement_kinds = asyncio.run(_statuses_and_kinds(database_url))
    assert statuses == {"in_stock", "retired"}
    assert movement_kinds == {"RESERVE", "CONSUME"}

    command.upgrade(config, "head")
    asyncio.run(_clear_seed(database_url))


async def _seed_held_stock(database_url: str) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await _seed_lot(connection)
            await _insert_unit(connection, status="reserved", revision_id=_REVISION)
            await _insert_unit(connection, status="in_use", revision_id=_REVISION)
            await _insert_movement(connection, kind="RESERVE", change=1, revision_id=_REVISION)
            await _insert_movement(connection, kind="CONSUME", change=-1, revision_id=_REVISION)
    finally:
        await engine.dispose()


async def _statuses_and_kinds(database_url: str) -> tuple[set[str], set[str]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            statuses = await connection.scalars(text("SELECT status FROM units"))
            kinds = await connection.scalars(
                text("SELECT kind FROM stock_movements WHERE revision_id IS NOT NULL")
            )
            return set(statuses), set(kinds)
    finally:
        await engine.dispose()


def test_0018_widened_status_check_accepts_the_new_unit_statuses(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    try:
        asyncio.run(_insert_held(database_url, status="reserved", revision_id=_REVISION))
        asyncio.run(_insert_held(database_url, status="in_use", revision_id=_REVISION))
    finally:
        asyncio.run(_clear_seed(database_url))


def test_0018_status_check_refuses_a_stray_status(database_url: str) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_held(database_url, status="in_orbit", revision_id=None))


def test_0018_revision_held_check_refuses_a_held_unit_without_a_revision(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_held(database_url, status="reserved", revision_id=None))


def test_0018_revision_held_check_refuses_an_in_stock_unit_with_a_revision(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_held(database_url, status="in_stock", revision_id=_REVISION))


def test_0018_revision_named_check_refuses_a_reserve_naming_no_revision(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_move(database_url, kind="RESERVE", change=1, revision_id=None))


def test_0018_revision_named_check_refuses_a_receive_naming_a_revision(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_move(database_url, kind="RECEIVE", change=1, revision_id=_REVISION))


def test_0018_revision_sign_check_refuses_a_reserve_with_a_negative_change(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_move(database_url, kind="RESERVE", change=-1, revision_id=_REVISION))


def test_0018_revision_sign_check_refuses_a_consume_with_a_positive_change(
    database_url: str,
) -> None:
    config = alembic_config(database_url)
    command.upgrade(config, "0018")
    with pytest.raises(IntegrityError):
        asyncio.run(_insert_move(database_url, kind="CONSUME", change=1, revision_id=_REVISION))


async def _insert_held(database_url: str, *, status: str, revision_id: str | None) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await _ensure_lot(connection)
            await _insert_unit(connection, status=status, revision_id=revision_id)
    finally:
        await engine.dispose()


async def _insert_move(
    database_url: str, *, kind: str, change: int, revision_id: str | None
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await _ensure_lot(connection)
            await _insert_movement(connection, kind=kind, change=change, revision_id=revision_id)
    finally:
        await engine.dispose()


async def _ensure_lot(connection: AsyncConnection) -> None:
    exists = await connection.scalar(text("SELECT 1 FROM stock_lots WHERE id = :id"), {"id": _LOT})
    if exists is None:
        await _seed_lot(connection)


async def _clear_seed(database_url: str) -> None:
    # The session's Postgres is shared, so a committing test clears its rows afterwards.
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text("TRUNCATE units, stock_movements, stock_lots, locations CASCADE")
            )
    finally:
        await engine.dispose()
