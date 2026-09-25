class FilesError(ValueError):
    """A value or change that breaks a files rule. The message is safe to show to users."""


class SubjectNotFoundError(FilesError):
    """The part (or, later, project) an upload names doesn't exist in this workspace."""


class AttachmentNotFoundError(FilesError):
    """No attachment with that id exists in this workspace."""


class AlreadyAttachedError(FilesError):
    """The same file is already attached to that subject: the same bytes attach once per part."""


class FileTooLargeError(FilesError):
    """An upload past MAX_FILE_SIZE, refused without reading more than the limit."""


class QuotaExceededError(FilesError):
    """The upload would take the workspace past its quota. The message says how much is left."""


class UnsupportedFileTypeError(FilesError):
    """The bytes aren't a PDF, PNG, JPEG or WebP, decided from their content, not their name."""
