import json
from datetime import UTC, datetime
from uuid import uuid7

import pytest

from wiredex.firmware.domain import errors
from wiredex.firmware.domain.errors import FirmwareError, FirmwareField, FirmwareRefusal
from wiredex.firmware.domain.flash import BlockingFlash, Flash, UnitCode
from wiredex.firmware.domain.semver import SemVer
from wiredex.firmware.domain.values import FlashId, UnitId, VersionId, WorkspaceId

NOW = datetime(2026, 9, 30, 3, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "error",
    [
        errors.FirmwareNotFoundError,
        errors.VersionNotFoundError,
        errors.SourceFileNotFoundError,
        errors.RevisionNotFoundError,
        errors.UnitNotFoundError,
        errors.FlashNotFoundError,
        errors.FirmwareRefusalError,
    ],
)
def test_every_firmware_error_is_a_firmware_error(error: type[Exception]) -> None:
    # The API answers a FirmwareError 422 unless a leaf has a status of its own.
    assert issubclass(error, FirmwareError)
    assert issubclass(error, ValueError)


@pytest.mark.parametrize(
    ("error", "code", "field"),
    [
        (errors.InvalidNameError, FirmwareRefusal.INVALID_NAME, FirmwareField.NAME),
        (errors.NameTakenError, FirmwareRefusal.NAME_TAKEN, FirmwareField.NAME),
        (errors.InvalidTargetError, FirmwareRefusal.INVALID_TARGET, FirmwareField.TARGET),
        (
            errors.InvalidDescriptionError,
            FirmwareRefusal.INVALID_DESCRIPTION,
            FirmwareField.DESCRIPTION,
        ),
        (errors.InvalidVersionError, FirmwareRefusal.INVALID_VERSION, FirmwareField.VERSION),
        (errors.VersionTakenError, FirmwareRefusal.VERSION_TAKEN, FirmwareField.VERSION),
        (
            errors.InvalidChangelogError,
            FirmwareRefusal.INVALID_CHANGELOG,
            FirmwareField.CHANGELOG,
        ),
        (errors.VersionReleasedError, FirmwareRefusal.VERSION_RELEASED, None),
        (errors.NoFilesError, FirmwareRefusal.NO_FILES, None),
        (errors.NoChangelogError, FirmwareRefusal.NO_CHANGELOG, FirmwareField.CHANGELOG),
        (errors.InvalidPathError, FirmwareRefusal.INVALID_PATH, FirmwareField.PATH),
        (errors.PathTakenError, FirmwareRefusal.PATH_TAKEN, FirmwareField.PATH),
        (errors.NotTextError, FirmwareRefusal.NOT_TEXT, FirmwareField.CONTENT),
        (errors.TooManyFilesError, FirmwareRefusal.TOO_MANY_FILES, FirmwareField.FILES),
        (errors.VersionTooLargeError, FirmwareRefusal.VERSION_TOO_LARGE, FirmwareField.FILES),
        (errors.NotReleasedError, FirmwareRefusal.NOT_RELEASED, FirmwareField.VERSION),
        (errors.UnitRetiredError, FirmwareRefusal.UNIT_RETIRED, FirmwareField.UNIT),
        (
            errors.FlashedInFutureError,
            FirmwareRefusal.FLASHED_IN_FUTURE,
            FirmwareField.FLASHED_AT,
        ),
        (errors.InvalidNotesError, FirmwareRefusal.INVALID_NOTES, FirmwareField.NOTES),
        (errors.VersionFlashedError, FirmwareRefusal.VERSION_FLASHED, None),
        (errors.FirmwareFlashedError, FirmwareRefusal.FIRMWARE_FLASHED, None),
        (errors.NameInTrashError, FirmwareRefusal.NAME_IN_TRASH, FirmwareField.NAME),
    ],
)
def test_every_refusal_carries_its_code_and_field(
    error: type[errors.FirmwareRefusalError],
    code: FirmwareRefusal,
    field: FirmwareField | None,
) -> None:
    # The web translates the code and marks the field, so each leaf has to carry both.
    assert issubclass(error, errors.FirmwareRefusalError)
    assert issubclass(error, FirmwareError)
    assert error.code is code
    assert error.field is field


def test_a_refusal_carries_the_item_it_names() -> None:
    refused = errors.PathTakenError("1.2.0 already has a file config.h", item="Config.h")
    assert refused.item == "Config.h"
    assert str(refused) == "1.2.0 already has a file config.h"
    assert errors.NoFilesError("1.2.0 has no file to release").item is None


@pytest.mark.parametrize("error", [errors.VersionFlashedError, errors.FirmwareFlashedError])
def test_a_flashed_refusal_carries_the_flashes_in_the_way(
    error: type[errors.VersionFlashedError | errors.FirmwareFlashedError],
) -> None:
    # 15's decision 6: the page lists them and offers to remove each, a deleted unit's included.
    gone = _a_blocking_flash(unit_present=False)
    held = _a_blocking_flash(unit_present=True)

    refused = error("1.0.0 is in the flash log of WX-U-0002", (gone, held), item="1.0.0")

    assert refused.flashes == (gone, held)
    assert str(refused) == "1.0.0 is in the flash log of WX-U-0002"
    assert refused.item == "1.0.0"
    assert error("Pico blink has flashed versions", ()).item is None


def _a_blocking_flash(*, unit_present: bool) -> BlockingFlash:
    flash = Flash(
        id=FlashId(uuid7()),
        workspace_id=WorkspaceId(uuid7()),
        unit_id=UnitId(uuid7()),
        unit_code=UnitCode("WX-U-0002"),
        version_id=VersionId(uuid7()),
        revision_id=None,
        flashed_at=NOW,
        notes=None,
        created_at=NOW,
    )
    return BlockingFlash(flash, SemVer(1, 0, 0), unit_present)


def test_a_refusal_writes_half_of_a_surrogate_pair_as_its_escape() -> None:
    # A JSON escape gives Python half of a surrogate pair, and the answer carrying a refusal is
    # UTF-8, which can't encode one: the refusal names it by its escape instead.
    half: str = json.loads('"\\ud800"')

    refused = errors.InvalidPathError(f"{half} can't be stored", item=f"src/{half}.h")

    assert str(refused) == "\\ud800 can't be stored"
    assert refused.item == "src/\\ud800.h"


def _refusal_leaves() -> list[type[errors.FirmwareRefusalError]]:
    return [
        leaf
        for leaf in vars(errors).values()
        if isinstance(leaf, type)
        and issubclass(leaf, errors.FirmwareRefusalError)
        and leaf is not errors.FirmwareRefusalError
    ]


def test_every_refusal_code_belongs_to_one_leaf() -> None:
    # The web has one sentence per code, so no code may go unraised or be raised by two leaves.
    assert sorted(leaf.code for leaf in _refusal_leaves()) == sorted(FirmwareRefusal)


def test_every_field_is_one_a_refusal_marks() -> None:
    # The wire union lists each field for the browser to mark, so none may go unused.
    marked = {leaf.field for leaf in _refusal_leaves() if leaf.field is not None}
    assert marked == set(FirmwareField)
