"""How typed text finds a record, the same everywhere a list or a picker narrows by text.

The text is read as words. A record is found when every word is somewhere in one of its
identifying fields, case aside and in any order: `m3 insert` finds *M3 x 4mm Heat In Brass
Insert*, which the text as one fragment never did. One word behaves as it always has.
"""

from collections.abc import Iterable


def words_of(text: str) -> tuple[str, ...]:
    """The text's words, lower-cased: what it is split into before anything is matched."""
    return tuple(text.lower().split())


def holds_words(text: str, fields: Iterable[object]) -> bool:
    """Whether every word of TEXT is in one of FIELDS, read as text, None left out. The
    in-memory twin of `holding_words`, for the fakes and the domain's own filters. Text with
    no word in it matches everything, as an empty search does."""
    haystacks = [str(field).lower() for field in fields if field is not None]
    return all(any(word in haystack for haystack in haystacks) for word in words_of(text))
