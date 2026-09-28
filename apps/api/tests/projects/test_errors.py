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
