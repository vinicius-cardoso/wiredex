import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.files.domain.errors import UnsupportedFileTypeError
from wiredex.files.domain.values import MediaType

# The leading bytes of a real file of each accepted type, padded so a WebP has its form type.
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "

# Files a browser might run a script from, or that are simply not a document or a picture.
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'
SVG_WITH_DECLARATION = b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>'
HTML = b"<!DOCTYPE html><html><body></body></html>"
XML = b'<?xml version="1.0" encoding="UTF-8"?><root/>'


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (PDF, MediaType.PDF),
        (PNG, MediaType.PNG),
        (JPEG, MediaType.JPEG),
        (WEBP, MediaType.WEBP),
    ],
)
def test_the_four_signatures_are_sniffed(head: bytes, expected: MediaType) -> None:
    assert MediaType.sniff(head) is expected


def test_the_four_media_type_values() -> None:
    assert {t.value for t in MediaType} == {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
    }


@pytest.mark.parametrize(
    "head",
    [
        SVG,
        SVG_WITH_DECLARATION,
        HTML,
        XML,
        b"",  # empty bytes are no type
        b"RIFF\x24\x00\x00\x00WAVE",  # a RIFF that isn't WebP (a WAV)
        b"not a known file at all",
    ],
)
def test_anything_else_is_refused(head: bytes) -> None:
    with pytest.raises(UnsupportedFileTypeError):
        MediaType.sniff(head)


def test_a_png_named_pdf_is_still_a_png() -> None:
    """The name and the claimed type don't decide: only the bytes do (requirement 2.1).

    A PNG uploaded as `diagram.pdf` sniffs as a PNG, so the type on the row and the bytes
    served can never disagree with the content.
    """
    assert MediaType.sniff(PNG) is MediaType.PNG


# --- Property 1: sniffing decides by content alone ----------------------------

_SIGNATURES = [PDF, PNG, JPEG, WEBP]
_FORBIDDEN_STARTS = (b"<svg", b"<?xml", b"<!DOCTYPE", b"<html", b"<HTML")


@given(content=st.binary(min_size=0, max_size=64))
def test_sniffing_depends_on_content_alone(content: bytes) -> None:
    """Property 1: `sniff` takes only the bytes, no file name or claimed type, so its answer
    is a function of content alone; and it never accepts bytes that begin like SVG, HTML or
    XML, whose scripts a browser would run from Wiredex's own origin.

    That `sniff(head: bytes)` has no other parameter is what makes the name and the claimed
    type unable to influence the result: there is nowhere to pass them.

    Validates: Requirements 2.1, 2.2, 2.3
    """
    try:
        first = MediaType.sniff(content)
    except UnsupportedFileTypeError:
        # Refused bytes stay refused: the outcome is stable for the same content.
        with pytest.raises(UnsupportedFileTypeError):
            MediaType.sniff(content)
        return

    # Accepted: the same content sniffs to the same type every time.
    assert MediaType.sniff(content) is first
    # And an accepted file never begins like a script-carrying format.
    assert not content.startswith(_FORBIDDEN_STARTS)


@given(st.sampled_from(_SIGNATURES), st.binary(max_size=32))
def test_a_known_signature_is_accepted_whatever_follows(head: bytes, tail: bytes) -> None:
    """Bytes that begin with an accepted signature are accepted; the rest of the file is
    never consulted, so any trailing bytes leave the answer unchanged.

    Validates: Requirements 2.1, 2.2
    """
    assert MediaType.sniff(head + tail) is MediaType.sniff(head)
