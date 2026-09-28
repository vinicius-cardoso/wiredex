from enum import StrEnum
from typing import ClassVar


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


class BomField(StrEnum):
    """The field of a BOM line a refusal is about, which the editor marks (decision 17)."""

    PART = "part"
    DESIGNATORS = "designators"
    QUANTITY = "quantity"
    NOTES = "notes"


class ContentRefusal(StrEnum):
    """Why a change to a revision's content was refused, as a code the web translates.

    The API answers the English sentence beside it, as 07's intake answers its problem codes.
    """

    INVALID_DESIGNATOR = "invalid_designator"
    INVALID_RANGE = "invalid_range"
    REPEATED_DESIGNATOR = "repeated_designator"
    TOO_MANY_DESIGNATORS = "too_many_designators"


class ContentError(ProjectsError):
    """A refused change to a revision's content.

    `code` and `field` are the leaf's own, so they live on the class; a leaf naming a
    designator or a typed item carries it in `item`, which the editor shows beside the field.
    """

    code: ClassVar[ContentRefusal]
    field: ClassVar[BomField | None] = None

    def __init__(self, message: str, item: str | None = None) -> None:
        super().__init__(message)
        self.item = item


class InvalidDesignatorError(ContentError):
    """Text that isn't a designator like R1, or an item of a list that is neither a designator
    nor a range. The item is the text as read, so the owner sees what to fix."""

    code = ContentRefusal.INVALID_DESIGNATOR
    field = BomField.DESIGNATORS


class InvalidDesignatorRangeError(ContentError):
    """A range that doesn't run upwards within one prefix: `R4-R1`, `R3-R3`, `R1-C4`."""

    code = ContentRefusal.INVALID_RANGE
    field = BomField.DESIGNATORS


class RepeatedDesignatorError(ContentError):
    """A list naming one designator twice, directly or through a range."""

    code = ContentRefusal.REPEATED_DESIGNATOR
    field = BomField.DESIGNATORS


class TooManyDesignatorsError(ContentError):
    """More designators than one line may hold."""

    code = ContentRefusal.TOO_MANY_DESIGNATORS
    field = BomField.DESIGNATORS
