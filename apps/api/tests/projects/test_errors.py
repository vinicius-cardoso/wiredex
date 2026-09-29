from uuid import uuid7

import pytest

from wiredex.projects.domain import errors
from wiredex.projects.domain.errors import ProjectsError


@pytest.mark.parametrize(
    "error",
    [
        errors.ProjectNotFoundError,
        errors.RevisionNotFoundError,
        errors.DuplicateProjectNameError,
        errors.DuplicateRevisionLabelError,
        errors.LastRevisionError,
        errors.RevisionHoldsStockError,
        errors.NoLabelLeftError,
        errors.InvalidProjectNameError,
        errors.InvalidTextError,
        errors.InvalidSummaryError,
        errors.InvalidTagError,
        errors.TooManyTagsError,
        errors.InvalidRevisionLabelError,
        errors.BomLineNotFoundError,
    ],
)
def test_every_projects_error_is_a_projects_error(error: type[Exception]) -> None:
    # The API maps ProjectsError to 422 unless a leaf has its own status.
    assert issubclass(error, ProjectsError)
    assert issubclass(error, ValueError)


@pytest.mark.parametrize(
    ("error", "code", "field"),
    [
        (
            errors.InvalidDesignatorError,
            errors.ContentRefusal.INVALID_DESIGNATOR,
            errors.BomField.DESIGNATORS,
        ),
        (
            errors.InvalidDesignatorRangeError,
            errors.ContentRefusal.INVALID_RANGE,
            errors.BomField.DESIGNATORS,
        ),
        (
            errors.RepeatedDesignatorError,
            errors.ContentRefusal.REPEATED_DESIGNATOR,
            errors.BomField.DESIGNATORS,
        ),
        (
            errors.TooManyDesignatorsError,
            errors.ContentRefusal.TOO_MANY_DESIGNATORS,
            errors.BomField.DESIGNATORS,
        ),
        (
            errors.DesignatorTakenError,
            errors.ContentRefusal.DESIGNATOR_TAKEN,
            errors.BomField.DESIGNATORS,
        ),
        (
            errors.QuantityMismatchError,
            errors.ContentRefusal.QUANTITY_MISMATCH,
            errors.BomField.QUANTITY,
        ),
        (
            errors.InvalidLineQuantityError,
            errors.ContentRefusal.INVALID_QUANTITY,
            errors.BomField.QUANTITY,
        ),
        (errors.InvalidBomNotesError, errors.ContentRefusal.INVALID_NOTES, errors.BomField.NOTES),
        (errors.UnknownPartError, errors.ContentRefusal.UNKNOWN_PART, errors.BomField.PART),
        (errors.TooManyLinesError, errors.ContentRefusal.TOO_MANY_LINES, None),
        (errors.RevisionContentLockedError, errors.ContentRefusal.REVISION_LOCKED, None),
    ],
)
def test_every_content_error_carries_its_code_and_field(
    error: type[errors.ContentError],
    code: errors.ContentRefusal,
    field: errors.BomField | None,
) -> None:
    # The web translates the code and marks the field, so each leaf has to carry both.
    assert issubclass(error, errors.ContentError)
    assert issubclass(error, ProjectsError)
    assert error.code is code
    assert error.field is field


def test_a_content_error_carries_the_item_it_names() -> None:
    refused = errors.RepeatedDesignatorError("R1 is named twice", item="R1")
    assert refused.item == "R1"
    assert str(refused) == "R1 is named twice"
    assert errors.TooManyDesignatorsError("too many").item is None


def test_every_refusal_code_belongs_to_one_leaf() -> None:
    # The web has one sentence per code, so no code may go unraised or be raised by two leaves.
    leaves = [
        leaf
        for leaf in vars(errors).values()
        if isinstance(leaf, type)
        and issubclass(leaf, errors.ContentError)
        and leaf is not errors.ContentError
    ]
    assert sorted(leaf.code for leaf in leaves) == sorted(errors.ContentRefusal)


def test_a_taken_designator_carries_the_line_holding_it() -> None:
    line_id = uuid7()
    refused = errors.DesignatorTakenError("R7 is already on the line R5–R7", "R7", line_id, "R5–R7")
    assert (refused.item, refused.line_id, refused.line) == ("R7", line_id, "R5–R7")
    assert refused.code is errors.ContentRefusal.DESIGNATOR_TAKEN
