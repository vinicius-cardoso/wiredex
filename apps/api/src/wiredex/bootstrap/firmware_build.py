"""`wiredex firmware build`: compile a released version's source and keep the result with it.

The one command that runs on the owner's computer and not on the server (20-firmware-builds):
the server has no room for a toolchain, and the computer that flashes a board already has one.
It is a client of the API like the web is, so it lives in the composition root and imports no
module. It logs in for a bearer token (ADR 0008), reads the version's source, compiles it with
`arduino-cli`, zips the binaries with a manifest of their offsets, attaches the zip to the
version as a build, and ends its session whatever happened.

The HTTP side is a `Transport`, a function from a request to a response, so the flow is tested
against the real app without a socket and production gains no HTTP client: `urllib` is enough
for six requests. The compiler is a function too, faked the same way.
"""

import contextlib
import io
import json
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

MANIFEST = "manifest.json"
FORMAT = 1
ARDUINO = "arduino"
RELEASED = "released"
#: Hosts a password may travel to without TLS: the owner's own machine.
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: A build with its compile and upload: generous, since a first compile fills a cache.
TIMEOUT_SECONDS = 120


class BuildError(Exception):
    """Why no build was made, in a sentence the command prints as it is."""


@dataclass(frozen=True, slots=True)
class Image:
    """One binary of a build and where in the flash it goes."""

    file: str
    offset: int
    data: bytes


# --- The build's zip ------------------------------------------------------------------


def read_flash_args(text: str) -> list[tuple[int, str]]:
    """The offsets and file names in an ESP32 core's `flash_args`, the list it writes for
    esptool: a first line of options, then `0x1000 sketch.ino.bootloader.bin` a line. The
    build's own word on where each binary goes (requirement 5.6)."""
    placed: list[tuple[int, str]] = []
    for line in text.splitlines():
        offset, _, name = line.strip().partition(" ")
        if not offset.lower().startswith("0x") or not name.strip():
            continue
        try:
            placed.append((int(offset, 16), name.strip()))
        except ValueError as error:
            raise BuildError(f"flash_args names an offset that isn't one: {offset}") from error
    return placed


def images_of(build_dir: Path, sketch: str) -> list[Image]:
    """The binaries a compile left in BUILD_DIR, each with its offset.

    An ESP32 core says where they go in `flash_args`. A core that writes none, the ESP8266's,
    builds one image that starts the flash. Anything else is refused: an offset is never
    guessed here.
    """
    listing = build_dir / "flash_args"
    if listing.is_file():
        placed = read_flash_args(listing.read_text())
    elif (build_dir / f"{sketch}.ino.bin").is_file():
        placed = [(0, f"{sketch}.ino.bin")]
    else:
        placed = []
    if not placed:
        raise BuildError("the build doesn't say where its binaries go, so none is kept")
    images = []
    for offset, name in placed:
        binary = build_dir / name
        if not binary.is_file():
            raise BuildError(f"the build names {name}, which it didn't write")
        images.append(Image(Path(name).name, offset, binary.read_bytes()))
    return images


def bundle(images: Sequence[Image], board: str, tool: str, built_at: datetime) -> bytes:
    """The build as the browser reads it: a zip with `manifest.json` first, naming each binary
    and its offset, then the binaries at its root (requirement 2.1). The manifest comes first so
    the zip opens with a local file header, which is what the API sniffs a ZIP by."""
    manifest = {
        "format": FORMAT,
        "board": board,
        "tool": tool,
        "built_at": built_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "images": [{"file": image.file, "offset": image.offset} for image in images],
    }
    packed = io.BytesIO()
    with zipfile.ZipFile(packed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(MANIFEST, json.dumps(manifest, indent=2))
        for image in images:
            archive.writestr(image.file, image.data)
    return packed.getvalue()


# --- The API --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Request:
    method: str
    path: str
    headers: Mapping[str, str]
    body: bytes | None = None


@dataclass(frozen=True, slots=True)
class Response:
    status: int
    body: bytes


type Transport = Callable[[Request], Response]


def urllib_transport(base_url: str) -> Transport:
    """Requests sent to BASE_URL. Refused unless it is HTTPS or the owner's own machine: the
    first request carries a password."""
    url = urlsplit(base_url)
    if url.scheme not in {"http", "https"} or not url.hostname:
        raise BuildError(f"{base_url} isn't an address like https://wiredex.example.com")
    if url.scheme == "http" and url.hostname not in LOCAL_HOSTS:
        raise BuildError("the password is only sent over HTTPS, or to this computer")
    root = base_url.rstrip("/")

    def send(request: Request) -> Response:
        outgoing = urllib.request.Request(  # noqa: S310 - the scheme is checked above
            root + request.path,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with urllib.request.urlopen(outgoing, timeout=TIMEOUT_SECONDS) as answer:  # noqa: S310
                return Response(answer.status, answer.read())
        except urllib.error.HTTPError as refused:
            return Response(refused.code, refused.read())
        except OSError as error:
            raise BuildError(f"{root} couldn't be reached: {error}") from error

    return send


class Api:
    """The six requests a build makes, over a transport."""

    def __init__(self, send: Transport) -> None:
        self._send = send
        self._token: str | None = None

    def log_in(self, email: str, password: str) -> None:
        body = json.dumps({"email": email, "password": password}).encode()
        answer = self._send(
            Request("POST", "/api/auth/tokens", {"Content-Type": "application/json"}, body)
        )
        if answer.status != HTTPStatus.OK:
            raise BuildError(f"the login was refused: {_detail(answer)}")
        self._token = str(json.loads(answer.body)["token"])

    def log_out(self) -> None:
        """Ends the session the login opened. A failure is swallowed: there is nothing more to
        do about it, and the build's own outcome is what the owner needs to read."""
        if self._token is None:
            return
        with contextlib.suppress(BuildError):
            self._send(Request("POST", "/api/auth/logout", self._headers()))
        self._token = None

    def firmware_named(self, name: str) -> list[dict[str, Any]]:
        """Every firmware whose name is exactly NAME, ignoring case, as the names are unique."""
        found = self._get(f"/api/firmware?search={quote(name)}")
        return [one for one in found if str(one["name"]).casefold() == name.casefold()]

    def firmware(self, firmware_id: str) -> dict[str, Any]:
        found: dict[str, Any] = self._get(f"/api/firmware/{firmware_id}")
        return found

    def version(self, version_id: str) -> dict[str, Any]:
        found: dict[str, Any] = self._get(f"/api/firmware/versions/{version_id}")
        return found

    def attach_build(self, version_id: str, title: str, data: bytes) -> dict[str, Any]:
        fields = {"subject": f"firmware_version:{version_id}", "kind": "firmware_build"}
        content_type, body = _multipart({**fields, "title": title}, "build.zip", data)
        answer = self._send(
            Request(
                "POST",
                "/api/files/attachments",
                {**self._headers(), "Content-Type": content_type},
                body,
            )
        )
        if answer.status != HTTPStatus.CREATED:
            raise BuildError(f"the build couldn't be stored: {_detail(answer)}")
        stored: dict[str, Any] = json.loads(answer.body)
        return stored

    def _get(self, path: str) -> Any:
        answer = self._send(Request("GET", path, self._headers()))
        if answer.status != HTTPStatus.OK:
            raise BuildError(f"{path} answered {answer.status}: {_detail(answer)}")
        return json.loads(answer.body)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


def _detail(answer: Response) -> str:
    """The API's own sentence when it sent one, the status when it didn't."""
    try:
        detail = json.loads(answer.body).get("detail")
    except ValueError, AttributeError:
        detail = None
    if isinstance(detail, dict):
        detail = detail.get("message")
    return detail if isinstance(detail, str) and detail else f"HTTP {answer.status}"


def _multipart(fields: Mapping[str, str], filename: str, data: bytes) -> tuple[str, bytes]:
    """A form with one file, as the attachments route reads it."""
    boundary = f"wiredex-{uuid4().hex}"
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        for name, value in fields.items()
    ]
    parts.append(
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            "Content-Type: application/zip\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    return f"multipart/form-data; boundary={boundary}", b"".join(parts)


# --- The compiler ---------------------------------------------------------------------

#: Compiles the sketch folder for a board into the build folder; answers the tool's name and
#: version, as the manifest keeps them.
type Compiler = Callable[[Path, Path, str], str]


def arduino_cli(executable: str = "arduino-cli") -> Compiler:
    """`arduino-cli` on this computer, found before anything is asked of the API (5.2)."""
    found = shutil.which(executable)
    if found is None:
        raise BuildError(
            f"{executable} isn't installed or isn't on the PATH: see https://arduino.github.io/arduino-cli/"
        )

    def compile_sketch(sketch_dir: Path, build_dir: Path, board: str) -> str:
        command = [found, "compile", "--fqbn", board, "--build-path", str(build_dir)]
        done = subprocess.run(  # noqa: S603 - the executable is the one found above
            [*command, str(sketch_dir)], capture_output=True, text=True, check=False
        )
        if done.returncode != 0:
            raise BuildError(f"the compile failed:\n{(done.stdout + done.stderr).strip()}")
        said = subprocess.run(  # noqa: S603
            [found, "version"], capture_output=True, text=True, check=False
        )
        version = re.search(r"Version:\s*(\S+)", said.stdout)
        return f"arduino-cli {version.group(1)}" if version else "arduino-cli"

    return compile_sketch


# --- The build ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Built:
    """What a build stored: the attachment's title, its size and the binaries in it."""

    title: str
    size: int
    images: tuple[Image, ...]


def build_version(  # noqa: PLR0913 - the command's whole context, each part faked alone in tests
    api: Api,
    compiler: Compiler,
    *,
    name: str,
    number: str,
    workdir: Path,
    now: Callable[[], datetime],
) -> Built:
    """Reads the version, compiles it under WORKDIR and attaches the build. The caller has
    logged in and logs out; nothing is attached unless the compile succeeded."""
    firmware = _the_firmware(api, name)
    version = _the_version(api, firmware, number)
    board = str(firmware["target"])
    sketch_dir = _write_sketch(workdir, version["files"])
    build_dir = workdir / "build"
    build_dir.mkdir()

    tool = compiler(sketch_dir, build_dir, board)
    images = images_of(build_dir, sketch_dir.name)
    built_at = now()
    title = f"Build {built_at:%Y-%m-%d %H:%M} UTC · {tool}"
    data = bundle(images, board, tool, built_at)
    api.attach_build(str(version["id"]), title, data)
    return Built(title, len(data), tuple(images))


def _the_firmware(api: Api, name: str) -> dict[str, Any]:
    matches = api.firmware_named(name)
    if not matches:
        raise BuildError(f"there is no firmware named {name}")
    firmware = api.firmware(str(matches[0]["id"]))
    if firmware["framework"] != ARDUINO:
        raise BuildError(
            f"{firmware['name']} is {firmware['framework']} firmware, and this command builds"
            " Arduino sketches: build it with its own tool and add the zip on the version's page"
        )
    return firmware


def _the_version(api: Api, firmware: dict[str, Any], number: str) -> dict[str, Any]:
    wanted = number.strip().lower().removeprefix("v")
    summary = next((one for one in firmware["versions"] if one["version"] == wanted), None)
    if summary is None:
        raise BuildError(f"{firmware['name']} has no version {wanted}")
    if summary["status"] != RELEASED:
        raise BuildError(
            f"{firmware['name']} {wanted} is a draft, and a draft can still change: release it"
            " first"
        )
    return api.version(str(summary["id"]))


def _write_sketch(workdir: Path, files: Sequence[Mapping[str, Any]]) -> Path:
    """The version's files as a sketch `arduino-cli` accepts: a folder named after its main
    `.ino`, the first listed, which the API lists before every other file."""
    main = next((str(file["path"]) for file in files if str(file["path"]).endswith(".ino")), None)
    if main is None or "/" in main:
        raise BuildError("the version has no .ino sketch at its top level to build")
    sketch_dir = workdir / Path(main).stem
    sketch_dir.mkdir()
    for file in files:
        target = (sketch_dir / str(file["path"])).resolve()
        # The API refuses such a path, and a folder outside the sketch is still never written.
        if not target.is_relative_to(sketch_dir.resolve()):
            raise BuildError(f"{file['path']} would be written outside the sketch")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(file["content"]), encoding="utf-8", newline="\n")
    return sketch_dir
