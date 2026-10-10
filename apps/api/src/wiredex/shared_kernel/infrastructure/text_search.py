"""The SQL for finding records by typed text, one function for every module's lists and
pickers, so they all read the text the same way (`shared_kernel.domain.text`)."""

from typing import Any

from sqlalchemy import ColumnElement, and_, or_, true

from wiredex.shared_kernel.domain.text import words_of

# A typed `%`, `_` or backslash is matched as itself, not as a pattern.
LIKE_WILDCARDS = str.maketrans({"\\": "\\\\", "%": "\\%", "_": "\\_"})
LIKE_ESCAPE = "\\"


def holding_words(text: str, *columns: ColumnElement[Any]) -> ColumnElement[bool]:
    """Every word of TEXT in one of COLUMNS, case aside and in any order: an escaped `ILIKE`
    a word and a column, which a trigram index on the column serves. Text with no word in it
    narrows nothing."""
    words = words_of(text)
    if not words:
        return true()
    return and_(
        *(
            or_(
                *(
                    column.ilike(f"%{word.translate(LIKE_WILDCARDS)}%", escape=LIKE_ESCAPE)
                    for column in columns
                )
            )
            for word in words
        )
    )
