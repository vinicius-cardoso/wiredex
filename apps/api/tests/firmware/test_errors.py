import json

import pytest

from wiredex.firmware.domain import errors
from wiredex.firmware.domain.errors import FirmwareError, FirmwareField, FirmwareRefusal


@pytest.mark.parametrize(
    "error",
    [
        errors.FirmwareNotFoundError,
        errors.VersionNotFoundError,
        errors.SourceFileNotFoundError,
        errors.RevisionNotFoundError,
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
