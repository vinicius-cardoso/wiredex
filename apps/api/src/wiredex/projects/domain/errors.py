class ProjectsError(ValueError):
    """A value or change that breaks a projects rule. The message is safe to show to users."""


class ProjectNotFoundError(ProjectsError):
    pass


class RevisionNotFoundError(ProjectsError):
    pass


class DuplicateProjectNameError(ProjectsError):
    """Two projects of a workspace can't share a name, ignoring case: the list, the tag filter
    and the command palette would be ambiguous. The message names the project."""


class DuplicateRevisionLabelError(ProjectsError):
    """Two revisions of one project can't share a label, ignoring case."""


class LastRevisionError(ProjectsError):
    """A project always keeps a revision, so the latest always has an answer: deleting its only
    one is refused, and deleting the project is the way to remove it."""


class RevisionInUseError(ProjectsError):
    """Only a draft can be deleted, so a revision that was reserved, built or dismantled, or a
    project holding one, stays. Unreachable before 10-build-lifecycle moves a status."""


class NoLabelLeftError(ProjectsError):
    """No label was given and the latest one can't be stepped within 16 characters."""


class InvalidProjectNameError(ProjectsError):
    """A project name that is blank or longer than its cap."""


class InvalidTextError(ProjectsError):
    """A description or notes that are blank or longer than their cap."""


class InvalidSummaryError(ProjectsError):
    """A revision summary that is blank or longer than its cap."""


class InvalidTagError(ProjectsError):
    """A tag that is blank, too long, or holds a comma or a control character."""


class TooManyTagsError(ProjectsError):
    """More distinct tags than a project, or a filter, may carry."""


class InvalidRevisionLabelError(ProjectsError):
    """A label outside its ASCII alphabet or length, or starting or ending with '.', '-' or '_'."""
