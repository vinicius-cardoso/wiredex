"""Text UTF-8 can encode, which is every code point but half of a surrogate pair.

A JSON escape such as `\\ud800` gives Python half of a pair, and UTF-8 is what PostgreSQL
stores text in and what the API answers in. So a value refuses text holding one, and a refusal
naming such text writes it as its escape.
"""


def encodes(text: str) -> bool:
    """Whether UTF-8 can encode the text: not when it holds half of a surrogate pair."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def escaped(text: str) -> str:
    """The text with each half of a surrogate pair written as its escape, `\\ud800`, so UTF-8
    can encode it. Text UTF-8 already encodes comes back as it is."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")
