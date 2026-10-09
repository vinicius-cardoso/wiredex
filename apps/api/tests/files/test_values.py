import re
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from wiredex.files.domain.errors import FilesError, UnsupportedFileTypeError
from wiredex.files.domain.values import (
    MAX_FILE_SIZE,
    MAX_TITLE_LENGTH,
    AttachmentKind,
    AttachmentTitle,
    FileSize,
    MediaType,
    Sha256,
    Subject,
    SubjectKind,
)

# --- Sha256 -------------------------------------------------------------------

VALID_DIGEST = "a" * 64


def test_a_sha256_is_sixty_four_hex_characters() -> None:
    assert str(Sha256(VALID_DIGEST)) == VALID_DIGEST


def test_a_sha256_is_lower_cased_and_trimmed() -> None:
    assert str(Sha256(f"  {'A' * 64}  ")) == "a" * 64


@pytest.mark.parametrize(
    "text",
    [
        "",
        "a" * 63,  # one short
        "a" * 65,  # one long
        "g" * 64,  # not hex
        "a" * 63 + "z",
    ],
)
def test_a_sha256_refuses_anything_that_is_not_sixty_four_hex(text: str) -> None:
    with pytest.raises(FilesError, match="SHA-256"):
        Sha256(text)


# --- FileSize -----------------------------------------------------------------


def test_max_file_size_is_twenty_five_mebibytes() -> None:
    assert MAX_FILE_SIZE == 25 * 1024 * 1024


@pytest.mark.parametrize("size", [1, 1024, MAX_FILE_SIZE])
def test_a_file_size_accepts_one_byte_up_to_the_cap(size: int) -> None:
    assert int(FileSize(size)) == size


@pytest.mark.parametrize("size", [0, -1, MAX_FILE_SIZE + 1])
def test_a_file_size_refuses_empty_and_over_the_cap(size: int) -> None:
    with pytest.raises(FilesError, match=f"between 1 and {MAX_FILE_SIZE} bytes"):
        FileSize(size)


# --- AttachmentKind -----------------------------------------------------------


def test_the_seven_kinds_exist() -> None:
    assert {k.value for k in AttachmentKind} == {
        "datasheet",
        "image",
        "pinout_diagram",
        "schematic",
        "gerbers",
        "firmware_build",
        "other",
    }


@pytest.mark.parametrize(
    ("kind", "subject"), [(kind, subject) for kind in AttachmentKind for subject in SubjectKind]
)
def test_a_build_goes_on_a_firmware_version_and_nothing_else_does(
    kind: AttachmentKind, subject: SubjectKind
) -> None:
    # 20-firmware-builds, requirement 1.8.
    build = kind is AttachmentKind.FIRMWARE_BUILD
    version = subject is SubjectKind.FIRMWARE_VERSION
    assert kind.fits(subject) is (build == version)


# The design's table (08's decision 13): what the web pre-selects, per subject and type. A
# project refuses a PDF and a ZIP, so those suggest `other` and the upload is refused anyway.
SUGGESTED = {
    SubjectKind.PART: {
        MediaType.PDF: AttachmentKind.DATASHEET,
        MediaType.ZIP: AttachmentKind.OTHER,
    },
    SubjectKind.PROJECT: {
        MediaType.PDF: AttachmentKind.OTHER,
        MediaType.ZIP: AttachmentKind.OTHER,
    },
    SubjectKind.REVISION: {
        MediaType.PDF: AttachmentKind.SCHEMATIC,
        MediaType.ZIP: AttachmentKind.GERBERS,
    },
}
IMAGES = (MediaType.PNG, MediaType.JPEG, MediaType.WEBP)


@pytest.mark.parametrize(
    ("subject", "media_type"),
    [(subject, media_type) for subject in SubjectKind for media_type in MediaType],
)
def test_a_kind_is_suggested_per_subject_and_media_type(
    subject: SubjectKind, media_type: MediaType
) -> None:
    if subject is SubjectKind.FIRMWARE_VERSION:
        # Whatever is sent, since a version holds builds alone (20-firmware-builds, 1.8).
        assert AttachmentKind.suggested_for(media_type, subject) == AttachmentKind.FIRMWARE_BUILD
        return
    expected = AttachmentKind.IMAGE if media_type in IMAGES else SUGGESTED[subject][media_type]
    assert AttachmentKind.suggested_for(media_type, subject) == expected


@pytest.mark.parametrize("subject", [SubjectKind.PART, SubjectKind.PROJECT, SubjectKind.REVISION])
def test_an_unknown_media_type_suggests_other(subject: SubjectKind) -> None:
    assert AttachmentKind.suggested_for("application/octet-stream", subject) == AttachmentKind.OTHER


# --- MediaType.previewable ----------------------------------------------------


@pytest.mark.parametrize("media_type", list(MediaType))
def test_only_a_zip_is_not_previewable(media_type: MediaType) -> None:
    # A browser shows a PDF and the images in place; a ZIP it can only save (08's 7.4).
    assert media_type.previewable is (media_type is not MediaType.ZIP)


# --- AttachmentTitle ----------------------------------------------------------


def test_a_title_is_trimmed_and_has_its_whitespace_collapsed() -> None:
    assert str(AttachmentTitle("  BME280   datasheet  ")) == "BME280 datasheet"


def test_a_title_accepts_its_cap_and_refuses_one_character_more() -> None:
    assert str(AttachmentTitle("x" * MAX_TITLE_LENGTH)) == "x" * MAX_TITLE_LENGTH
    with pytest.raises(FilesError, match=f"between 1 and {MAX_TITLE_LENGTH}"):
        AttachmentTitle("x" * (MAX_TITLE_LENGTH + 1))


@pytest.mark.parametrize("text", ["", "   ", "\t\n"])
def test_a_blank_title_is_never_a_title(text: str) -> None:
    with pytest.raises(FilesError):
        AttachmentTitle(text)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("BME280.pdf", "BME280.pdf"),
        ("/home/vini/datasheets/BME280.pdf", "BME280.pdf"),
        ("C:\\Users\\vini\\BME280.pdf", "BME280.pdf"),
        ("  spaced name.png  ", "spaced name.png"),
    ],
)
def test_a_title_from_a_filename_strips_the_path(name: str, expected: str) -> None:
    assert str(AttachmentTitle.from_filename(name)) == expected


def test_a_title_from_a_long_filename_is_capped() -> None:
    title = AttachmentTitle.from_filename("x" * 500 + ".pdf")
    assert len(str(title)) == MAX_TITLE_LENGTH


@pytest.mark.parametrize("name", ["", "   ", "/", "///", "a/b/"])
def test_a_filename_with_nothing_usable_is_refused(name: str) -> None:
    with pytest.raises(FilesError):
        AttachmentTitle.from_filename(name)


# --- Subject ------------------------------------------------------------------


def test_a_part_subject_round_trips() -> None:
    part_id = uuid4()
    subject = Subject.parse(f"part:{part_id}")
    assert subject.kind == SubjectKind.PART
    assert subject.id == part_id
    assert str(subject) == f"part:{part_id}"


def test_a_subject_built_directly_serializes() -> None:
    part_id = UUID("11111111-1111-1111-1111-111111111111")
    assert str(Subject(SubjectKind.PART, part_id)) == f"part:{part_id}"


@pytest.mark.parametrize("kind", [SubjectKind.PROJECT, SubjectKind.REVISION])
def test_a_project_and_a_revision_subject_parse(kind: SubjectKind) -> None:
    # 08's requirement 7: a project's photos and a revision's files are attachments too.
    subject_id = uuid4()
    subject = Subject.parse(f"{kind}:{subject_id}")
    assert subject == Subject(kind, subject_id)
    assert str(subject) == f"{kind}:{subject_id}"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "part",  # no separator
        "part:not-a-uuid",
        "revision:not-a-uuid",
        f"nonsense:{uuid4()}",
    ],
)
def test_a_bad_subject_is_refused(text: str) -> None:
    with pytest.raises(FilesError):
        Subject.parse(text)


# What each kind takes (08's requirements 7.1, 7.2): a project photos only, the others all.
ACCEPTED = {
    SubjectKind.PART: set(MediaType),
    SubjectKind.PROJECT: {MediaType.PNG, MediaType.JPEG, MediaType.WEBP},
    SubjectKind.REVISION: set(MediaType),
    SubjectKind.FIRMWARE_VERSION: {MediaType.ZIP},
}


def test_a_subject_is_named_in_words_and_says_what_it_takes() -> None:
    assert SubjectKind.FIRMWARE_VERSION.noun == "firmware version"
    assert SubjectKind.PART.noun == "part"
    assert "ZIP" in SubjectKind.FIRMWARE_VERSION.takes
    assert "photos" in SubjectKind.PROJECT.takes


@pytest.mark.parametrize(
    ("kind", "media_type"), [(kind, media_type) for kind in SubjectKind for media_type in MediaType]
)
def test_each_kind_accepts_its_own_types(kind: SubjectKind, media_type: MediaType) -> None:
    assert kind.accepts(media_type) is (media_type in ACCEPTED[kind])


# --- Property 5: a title survives any file name -------------------------------


@given(st.text())
def test_a_title_survives_any_filename(name: str) -> None:
    """Property 5: from_filename gives a non-empty title of at most 120 characters with no
    path separator, or a refusal for a name with nothing usable in it.

    Validates: Requirements 1.2
    """
    try:
        title = str(AttachmentTitle.from_filename(name))
    except FilesError:
        # Refused: then the last path segment has nothing usable left after trimming.
        last_segment = re.split(r"[/\\]", name)[-1]
        assert last_segment.strip() == ""
        return
    assert 1 <= len(title) <= MAX_TITLE_LENGTH
    assert "/" not in title
    assert "\\" not in title


# UnsupportedFileTypeError is a leaf of the error table; it is a FilesError like the rest.
def test_unsupported_file_type_is_a_files_error() -> None:
    assert issubclass(UnsupportedFileTypeError, FilesError)
