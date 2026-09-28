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
        errors.RevisionInUseError,
        errors.NoLabelLeftError,
        errors.InvalidProjectNameError,
        errors.InvalidTextError,
        errors.InvalidSummaryError,
        errors.InvalidTagError,
        errors.TooManyTagsError,
        errors.InvalidRevisionLabelError,
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
