"""What history refuses."""


class HistoryError(ValueError):
    """A request history can't answer. The message is safe to show to users."""


class ChangeNotFoundError(HistoryError):
    """A change the workspace doesn't hold, another bench's included: a 404, so an id says
    nothing about another workspace (17-history, requirement 4.6)."""


class RecordNotFoundError(HistoryError):
    """A record that isn't live in the workspace: never there, another bench's, in the trash or
    deleted for good. Its timeline is a 404, as its page is (requirement 3.2)."""


class InvalidHistoryCursorError(HistoryError):
    """A cursor the API didn't give (requirement 2.5). A client only echoes the last page's."""


class InvalidHistoryFilterError(HistoryError):
    """A text to narrow the activity by that is longer than the box it is typed in."""


class NotRestorableError(HistoryError):
    """A change that can't be restored, or a restore the record's module refused: a 409, with
    the sentence saying why (requirements 4.3 to 4.5)."""
