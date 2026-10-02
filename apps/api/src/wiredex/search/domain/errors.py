"""What the search refuses."""


class SearchError(ValueError):
    """A search the workspace can't be asked. The message is safe to show to users."""


class InvalidSearchError(SearchError):
    """A text that is blank once trimmed, or longer than a search takes (requirement 1.5)."""
