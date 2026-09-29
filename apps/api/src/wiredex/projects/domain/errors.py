from enum import StrEnum
from typing import ClassVar
from uuid import UUID


class ProjectsError(ValueError):
    """A value or change that breaks a projects rule. The message is safe to show to users."""


class ProjectNotFoundError(ProjectsError):
    pass


class RevisionNotFoundError(ProjectsError):
    pass


class BomLineNotFoundError(ProjectsError):
    """A line that isn't on the revision it was named under, another revision's included."""


class DuplicateProjectNameError(ProjectsError):
    """Two projects of a workspace can't share a name, ignoring case: the list, the tag filter
    and the command palette would be ambiguous. The message names the project."""


class DuplicateRevisionLabelError(ProjectsError):
    """Two revisions of one project can't share a label, ignoring case."""


class LastRevisionError(ProjectsError):
    """A project always keeps a revision, so the latest always has an answer: deleting its only
    one is refused, and deleting the project is the way to remove it."""


class RevisionHoldsStockError(ProjectsError):
    """A revision that holds stock, reserved or built, can't be deleted, nor a project holding
    one: it is the record of stock set aside for it, and its reservation must be cancelled or
    its build dismantled first (requirements 9.1, 9.3). A draft and a dismantled revision hold
    nothing and go (decision 7)."""


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
    DESIGNATOR_TAKEN = "designator_taken"
    QUANTITY_MISMATCH = "quantity_mismatch"
    INVALID_QUANTITY = "invalid_quantity"
    INVALID_NOTES = "invalid_notes"
    UNKNOWN_PART = "unknown_part"
    TOO_MANY_LINES = "too_many_lines"
    REVISION_LOCKED = "revision_locked"


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


class DesignatorTakenError(ContentError):
    """A designator another line of the revision holds (requirement 4.6).

    It carries that line's id and canonical text, so the refusal reads *R7 is already on the
    line R5–R7* without the domain knowing part names.
    """

    code = ContentRefusal.DESIGNATOR_TAKEN
    field = BomField.DESIGNATORS

    def __init__(self, message: str, item: str, line_id: UUID, line: str) -> None:
        super().__init__(message, item)
        self.line_id = line_id
        self.line = line


class QuantityMismatchError(ContentError):
    """A quantity given beside designators that disagrees with their count (decision 7)."""

    code = ContentRefusal.QUANTITY_MISMATCH
    field = BomField.QUANTITY


class InvalidLineQuantityError(ContentError):
    """A line without designators whose quantity is missing or outside 1 to 10,000."""

    code = ContentRefusal.INVALID_QUANTITY
    field = BomField.QUANTITY


class InvalidBomNotesError(ContentError):
    """A line's notes longer than their cap once collapsed."""

    code = ContentRefusal.INVALID_NOTES
    field = BomField.NOTES


class UnknownPartError(ContentError):
    """A part the workspace's catalog doesn't hold, another workspace's included (9.3)."""

    code = ContentRefusal.UNKNOWN_PART
    field = BomField.PART


class TooManyLinesError(ContentError):
    """A line past the most a revision's BOM holds."""

    code = ContentRefusal.TOO_MANY_LINES


class RevisionContentLockedError(ContentError):
    """A change to the content of a revision that isn't a draft (decision 11). A 409, as a
    taken designator is: the request was fine, the revision's state refuses it."""

    code = ContentRefusal.REVISION_LOCKED


class NetField(StrEnum):
    """The field of a net a refusal is about, which the netlist editor marks (11's decision 12)."""

    NAME = "name"
    COLOR = "color"
    NOTES = "notes"
    PINS = "pins"


class NetRefusal(StrEnum):
    """Why a net write was refused, as a code the web translates (11's Error Handling)."""

    INVALID_NET_NAME = "invalid_net_name"
    NET_NAME_TAKEN = "net_name_taken"
    INVALID_NOTES = "invalid_notes"
    INVALID_PIN_REF = "invalid_pin_ref"
    UNKNOWN_DESIGNATOR = "unknown_designator"
    UNKNOWN_PART = "unknown_part"
    UNKNOWN_PIN = "unknown_pin"
    AMBIGUOUS_PIN = "ambiguous_pin"
    REPEATED_PIN = "repeated_pin"
    NO_PINS = "no_pins"
    TOO_MANY_PINS = "too_many_pins"
    TOO_MANY_NETS = "too_many_nets"
    REVISION_LOCKED = "revision_locked"


class NetError(ProjectsError):
    """A refused net write, with its code, its field and the reference or text it names.

    A family of its own beside `ContentError`, whose codes and fields are the BOM's: the two
    editors translate different codes, and each wire union is kept in step with one enum.
    """

    code: ClassVar[NetRefusal]
    field: ClassVar[NetField | None] = None

    def __init__(self, message: str, item: str | None = None) -> None:
        super().__init__(message)
        self.item = item


class InvalidPinReferenceError(NetError):
    """Text that isn't a designator, a dot and a pin: no dot, a left half that isn't a
    designator, an empty pin, or a pin that isn't a pin number on a part with no pinout."""

    code = NetRefusal.INVALID_PIN_REF
    field = NetField.PINS
