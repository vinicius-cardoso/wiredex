"""How inventory compares a name someone typed: catalog's folding, restated, because
inventory can't import catalog (ADR 0001).

A sheet's headers and a location's path are both compared this way, so a sheet typed on
another keyboard still finds `Localização` and `Gaveta três`.
"""

import unicodedata


def fold(text: str) -> str:
    """The text as it is compared. NFKC first, so a full-width letter or a ligature reads as
    its plain letters; then NFKD after case folding, whose combining marks are the accents
    dropped (casefold itself can leave one, as İ becomes i with a dot above); then spacing
    collapsed."""
    folded = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", text).casefold())
    bare = "".join(char for char in folded if not unicodedata.combining(char))
    return " ".join(bare.split())
