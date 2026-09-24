import uuid


class Uuid7Generator:
    """UUIDv7 identifiers: time-ordered, so new rows land at the end of an index."""

    def new_id(self) -> uuid.UUID:
        return uuid.uuid7()
