"""`wiredex firmware build` over a fake API and a fake compiler (20-firmware-builds).

The API is a function from a request to a response, so the fake here answers the six requests
as the real routes do, and keeps what was sent. The integration test runs the same flow through
the real app.
"""

import io
import json
import threading
import zipfile
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner, Result

from wiredex.bootstrap import firmware_build
from wiredex.bootstrap.cli import cli
from wiredex.bootstrap.firmware_build import (
    Api,
    BuildError,
    Built,
    Image,
    Request,
    Response,
    arduino_cli,
    build_version,
    bundle,
    images_of,
    read_flash_args,
    urllib_transport,
)

NOW = datetime(2026, 10, 9, 21, 40, tzinfo=UTC)
FLASH_ARGS = (
    "--flash-mode dio --flash-freq 80m --flash-size 4MB\n"
    "0x1000 blink.ino.bootloader.bin\n"
    "0x8000 blink.ino.partitions.bin\n"
    "0xe000 boot_app0.bin\n"
    "0x10000 blink.ino.bin\n"
)
SKETCH = "void setup() {}\nvoid loop() {}\n"


class FakeWiredex:
    """The routes a build calls, over one firmware with a released 1.0.0 and a draft 1.1.0."""

    def __init__(self) -> None:
        self.requests: list[Request] = []
        self.sessions: set[str] = set()
        self.attached: list[bytes] = []
        self.framework = "arduino"
        self.files = [
            {"path": "blink.ino", "content": SKETCH},
            {"path": "src/pins.h", "content": "#define LED 2\n"},
        ]
        self.refuse_upload: tuple[int, dict[str, Any]] | None = None

    def __call__(self, request: Request) -> Response:
        self.requests.append(request)
        if request.path == "/api/auth/tokens":
            sent = json.loads(request.body or b"{}")
            if sent["password"] != "correct horse battery":
                return _json(401, {"detail": "wrong email or password"})
            self.sessions.add("token-1")
            return _json(200, {"token": "token-1", "user": {}})
        if request.headers.get("Authorization") != "Bearer token-1" or not self.sessions:
            return _json(401, {"detail": "log in first"})
        if request.path == "/api/auth/logout":
            self.sessions.clear()
            return Response(204, b"")
        return self._answer(request)

    def _answer(self, request: Request) -> Response:
        summary = {"id": "fw-1", "name": "Blink", "target": "esp32:esp32:esp32"}
        if request.path.startswith("/api/firmware?search="):
            other = {"id": "fw-2", "name": "Blink count"}
            return _json(200, [other, summary] if "blink" in request.path.lower() else [])
        if request.path == "/api/firmware/fw-1":
            versions = [
                {"id": "v-110", "version": "1.1.0", "status": "draft"},
                {"id": "v-100", "version": "1.0.0", "status": "released"},
            ]
            return _json(200, {**summary, "framework": self.framework, "versions": versions})
        if request.path == "/api/firmware/versions/v-100":
            return _json(200, {"id": "v-100", "version": "1.0.0", "files": self.files})
        if request.path == "/api/files/attachments" and request.method == "POST":
            if self.refuse_upload:
                return _json(*self.refuse_upload)
            self.attached.append(request.body or b"")
            return _json(201, {"id": "a-1"})
        return _json(404, {"detail": {"message": "that doesn't exist"}})


def _json(status: int, body: object) -> Response:
    return Response(status, json.dumps(body).encode())


class FakeCompiler:
    """Writes what an ESP32 core's compile leaves in the build folder, and keeps its inputs."""

    def __init__(self) -> None:
        self.compiled: list[tuple[list[str], str]] = []
        self.fail_with: str | None = None

    def __call__(self, sketch_dir: Path, build_dir: Path, board: str) -> str:
        files = sorted(
            str(path.relative_to(sketch_dir.parent))
            for path in sketch_dir.rglob("*")
            if path.is_file()
        )
        self.compiled.append((files, board))
        if self.fail_with:
            raise BuildError(f"the compile failed:\n{self.fail_with}")
        (build_dir / "flash_args").write_text(FLASH_ARGS)
        for name in ("blink.ino.bootloader.bin", "blink.ino.partitions.bin", "boot_app0.bin"):
            (build_dir / name).write_bytes(name.encode())
        (build_dir / "blink.ino.bin").write_bytes(b"\xe9app")
        (build_dir / "blink.ino.merged.bin").write_bytes(b"\xff" * 64)
        return "arduino-cli 1.4.1"


def _logged_in(server: FakeWiredex) -> Api:
    api = Api(server)
    api.log_in("owner@example.com", "correct horse battery")
    return api


def _build(
    server: FakeWiredex,
    compiler: FakeCompiler,
    tmp_path: Path,
    *,
    name: str = "blink",
    number: str = "1.0.0",
) -> Built:
    api = _logged_in(server)
    return build_version(api, compiler, name=name, number=number, workdir=tmp_path, now=lambda: NOW)


# --- The build's zip ------------------------------------------------------------------


def test_flash_args_gives_each_binary_its_offset_and_skips_the_options() -> None:
    assert read_flash_args(FLASH_ARGS) == [
        (0x1000, "blink.ino.bootloader.bin"),
        (0x8000, "blink.ino.partitions.bin"),
        (0xE000, "boot_app0.bin"),
        (0x10000, "blink.ino.bin"),
    ]
    assert read_flash_args("--flash-mode dio\n\n") == []
    with pytest.raises(BuildError, match="isn't one: 0xzz"):
        read_flash_args("0xzz app.bin\n")


def test_an_esp8266_build_is_one_image_at_the_start_of_the_flash(tmp_path: Path) -> None:
    (tmp_path / "blink.ino.bin").write_bytes(b"app")
    assert images_of(tmp_path, "blink") == [Image("blink.ino.bin", 0, b"app")]


def test_a_build_that_doesnt_place_its_binaries_is_refused(tmp_path: Path) -> None:
    with pytest.raises(BuildError, match="doesn't say where its binaries go"):
        images_of(tmp_path, "blink")
    (tmp_path / "flash_args").write_text("0x10000 blink.ino.bin\n")
    with pytest.raises(BuildError, match=r"names blink\.ino\.bin, which it didn't write"):
        images_of(tmp_path, "blink")


def test_a_bundle_opens_with_its_manifest_and_holds_each_binary() -> None:
    images = [Image("boot.bin", 0x1000, b"boot"), Image("app.bin", 0x10000, b"app" * 100)]
    data = bundle(images, "esp32:esp32:esp32", "arduino-cli 1.4.1", NOW)

    # A local file header first: what the API sniffs a ZIP by.
    assert data.startswith(b"PK\x03\x04")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.namelist() == ["manifest.json", "boot.bin", "app.bin"]
        assert json.loads(archive.read("manifest.json")) == {
            "format": 1,
            "board": "esp32:esp32:esp32",
            "tool": "arduino-cli 1.4.1",
            "built_at": "2026-10-09T21:40:00Z",
            "images": [
                {"file": "boot.bin", "offset": 0x1000},
                {"file": "app.bin", "offset": 0x10000},
            ],
        }
        assert archive.read("app.bin") == b"app" * 100
        assert archive.getinfo("app.bin").compress_type == zipfile.ZIP_DEFLATED


# --- The flow -------------------------------------------------------------------------


def test_a_released_version_is_compiled_and_its_build_attached(tmp_path: Path) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()

    built = _build(server, compiler, tmp_path, number="v1.0.0")

    # The version's files as a sketch named after its .ino, compiled for the firmware's board.
    assert compiler.compiled == [(["blink/blink.ino", "blink/src/pins.h"], "esp32:esp32:esp32")]
    assert built.title == "Build 2026-10-09 21:40 UTC · arduino-cli 1.4.1"
    assert [(image.file, image.offset) for image in built.images] == [
        ("blink.ino.bootloader.bin", 0x1000),
        ("blink.ino.partitions.bin", 0x8000),
        ("boot_app0.bin", 0xE000),
        ("blink.ino.bin", 0x10000),
    ]
    (form,) = server.attached
    assert b'name="subject"\r\n\r\nfirmware_version:v-100\r\n' in form
    assert b'name="kind"\r\n\r\nfirmware_build\r\n' in form
    assert 'name="title"\r\n\r\nBuild 2026-10-09 21:40 UTC · arduino-cli 1.4.1'.encode() in form
    # The zip rides in the form whole; the merged image, which holds the others, is left out.
    start = form.index(b"PK\x03\x04")
    with zipfile.ZipFile(io.BytesIO(form[start : form.rindex(b"\r\n--wiredex-")])) as archive:
        assert archive.namelist() == ["manifest.json", *[image.file for image in built.images]]
        assert archive.read("blink.ino.bin") == b"\xe9app"
    assert built.size == len(form[start : form.rindex(b"\r\n--wiredex-")])


@pytest.mark.parametrize(
    ("name", "number", "sentence"),
    [
        ("Blinker", "1.0.0", "there is no firmware named Blinker"),
        ("Blink", "2.0.0", "Blink has no version 2.0.0"),
        ("Blink", "1.1.0", "Blink 1.1.0 is a draft"),
    ],
)
def test_nothing_is_compiled_for_what_cant_be_built(
    tmp_path: Path, name: str, number: str, sentence: str
) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()
    with pytest.raises(BuildError, match=sentence):
        _build(server, compiler, tmp_path, name=name, number=number)
    assert compiler.compiled == []
    assert server.attached == []


def test_only_arduino_firmware_is_built(tmp_path: Path) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()
    server.framework = "platformio"
    with pytest.raises(BuildError, match="Blink is platformio firmware"):
        _build(server, compiler, tmp_path)
    assert compiler.compiled == []


def test_a_failed_compile_attaches_nothing_and_shows_the_compiler(tmp_path: Path) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()
    compiler.fail_with = "blink.ino:2:1: error: expected '}'"
    with pytest.raises(BuildError, match="expected '}'"):
        _build(server, compiler, tmp_path)
    assert server.attached == []


def test_a_version_needs_a_sketch_at_its_top_level(tmp_path: Path) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()
    server.files = [{"path": "main.cpp", "content": "int main() {}\n"}]
    with pytest.raises(BuildError, match=r"no \.ino sketch"):
        _build(server, compiler, tmp_path)


def test_a_file_is_never_written_outside_the_sketch(tmp_path: Path) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()
    server.files = [*server.files, {"path": "../../escape.h", "content": ""}]
    with pytest.raises(BuildError, match="outside the sketch"):
        _build(server, compiler, tmp_path)
    assert not (tmp_path.parent / "escape.h").exists()


def test_a_refused_upload_says_what_the_api_said(tmp_path: Path) -> None:
    server, compiler = FakeWiredex(), FakeCompiler()
    server.refuse_upload = (413, {"detail": "that would pass the workspace's quota"})
    with pytest.raises(BuildError, match="couldn't be stored: that would pass the workspace"):
        _build(server, compiler, tmp_path)


# --- The API --------------------------------------------------------------------------


def test_a_refused_login_stops_there_and_a_logout_ends_the_session() -> None:
    server = FakeWiredex()
    api = Api(server)
    with pytest.raises(BuildError, match="the login was refused: wrong email or password"):
        api.log_in("owner@example.com", "guess")
    # Never logged in, so there is no session to end and nothing is sent.
    api.log_out()
    assert [request.path for request in server.requests] == ["/api/auth/tokens"]

    api.log_in("owner@example.com", "correct horse battery")
    assert server.sessions
    api.log_out()
    assert not server.sessions
    assert server.requests[-1].headers == {"Authorization": "Bearer token-1"}


def test_a_refusal_with_no_sentence_is_named_by_its_status() -> None:
    api = Api(lambda _request: Response(502, b"<html>Bad gateway</html>"))
    with pytest.raises(BuildError, match="the login was refused: HTTP 502"):
        api.log_in("owner@example.com", "x")


def test_a_logout_that_cant_be_sent_doesnt_hide_the_builds_outcome() -> None:
    server = FakeWiredex()
    api = _logged_in(server)

    def unreachable(_request: Request) -> Response:
        raise BuildError("the server couldn't be reached")

    api._send = unreachable
    api.log_out()


def test_the_password_only_travels_over_https_or_to_this_computer() -> None:
    with pytest.raises(BuildError, match="only sent over HTTPS"):
        urllib_transport("http://wiredex.example.com")
    with pytest.raises(BuildError, match="isn't an address"):
        urllib_transport("wiredex.example.com")
    assert callable(urllib_transport("https://wiredex.example.com/"))
    assert callable(urllib_transport("http://localhost:9000"))


def test_requests_reach_a_server_and_a_refusal_comes_back_as_an_answer() -> None:
    seen: list[tuple[str, str, str | None, bytes]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = self.rfile.read(int(self.headers["Content-Length"]))
            seen.append((self.command, self.path, self.headers["Authorization"], body))
            refused = self.path.endswith("/refused")
            self.send_response(422 if refused else 201)
            self.end_headers()
            self.wfile.write(b'{"detail": "no"}' if refused else b'{"id": "a-1"}')

        def log_message(self, *_arguments: object) -> None:
            """Quiet: the default writes every request to stderr."""

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        send = urllib_transport(f"http://127.0.0.1:{server.server_port}/")
        headers = {"Authorization": "Bearer token-1"}
        assert send(Request("POST", "/api/files/attachments", headers, b"zip")) == Response(
            201, b'{"id": "a-1"}'
        )
        assert send(Request("POST", "/refused", headers, b"")) == Response(422, b'{"detail": "no"}')
        assert seen[0] == ("POST", "/api/files/attachments", "Bearer token-1", b"zip")
    finally:
        server.shutdown()
        server.server_close()

    with pytest.raises(BuildError, match="couldn't be reached"):
        send(Request("POST", "/api/auth/tokens", {}, b"{}"))


# --- The command ----------------------------------------------------------------------


def _run(
    monkeypatch: pytest.MonkeyPatch, server: FakeWiredex, *arguments: str, password: str
) -> tuple[Result, FakeCompiler]:
    compiler = FakeCompiler()
    monkeypatch.setattr(firmware_build, "urllib_transport", lambda _url: server)
    monkeypatch.setattr(firmware_build, "arduino_cli", lambda _path: compiler)
    options = ["--url", "http://localhost:9000", "--email", "owner@example.com"]
    result = CliRunner().invoke(
        cli, ["firmware", "build", *arguments, *options, "--password-stdin"], input=password + "\n"
    )
    return result, compiler


def test_the_command_builds_stores_and_logs_out(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeWiredex()
    result, _ = _run(monkeypatch, server, "Blink", "1.0.0", password="correct horse battery")

    assert result.exit_code == 0, result.output
    assert "Stored “Build " in result.output
    assert "0x10000  blink.ino.bin  (4 bytes)" in result.output
    assert len(server.attached) == 1
    assert not server.sessions
    # The password went in the login's body and nowhere else.
    assert all(b"correct horse" not in (r.body or b"") for r in server.requests[1:])


def test_the_command_logs_out_when_the_build_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeWiredex()
    result, compiler = _run(monkeypatch, server, "Blink", "1.1.0", password="correct horse battery")

    assert result.exit_code == 1
    assert "Error: Blink 1.1.0 is a draft" in result.output
    assert compiler.compiled == []
    assert not server.sessions
    assert server.requests[-1].path == "/api/auth/logout"


def test_the_command_stops_at_a_refused_login(monkeypatch: pytest.MonkeyPatch) -> None:
    server = FakeWiredex()
    result, _ = _run(monkeypatch, server, "Blink", "1.0.0", password="guess")

    assert result.exit_code == 1
    assert "Error: the login was refused" in result.output
    assert [request.path for request in server.requests] == ["/api/auth/tokens"]


def test_a_missing_arduino_cli_is_said_before_anything_is_asked() -> None:
    with pytest.raises(BuildError, match="no-such-arduino-cli isn't installed"):
        arduino_cli("no-such-arduino-cli")
    result = CliRunner().invoke(
        cli,
        ["firmware", "build", "Blink", "1.0.0", "--arduino-cli", "no-such-arduino-cli"],
        env={"WIREDEX_URL": "http://localhost:9000", "WIREDEX_EMAIL": "owner@example.com"},
    )
    assert result.exit_code == 1
    assert "isn't installed" in result.output


def test_the_compiler_runs_arduino_cli_and_names_its_version(tmp_path: Path) -> None:
    # A stand-in executable: it answers `version`, and fails a compile it is told to fail.
    script = tmp_path / "arduino-cli"
    script.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = version ]; then echo "arduino-cli  Version: 1.4.1 Commit: e394"; exit 0; fi\n'
        'echo "$@" > "$5/arguments"\n'
        'if [ -f "$6/fail" ]; then echo "error: expected }" >&2; exit 1; fi\n'
    )
    script.chmod(0o755)
    sketch, build = tmp_path / "blink", tmp_path / "build"
    sketch.mkdir()
    build.mkdir()
    compiler = arduino_cli(str(script))

    assert compiler(sketch, build, "esp32:esp32:esp32") == "arduino-cli 1.4.1"
    assert (build / "arguments").read_text().split() == [
        "compile",
        "--fqbn",
        "esp32:esp32:esp32",
        "--build-path",
        str(build),
        str(sketch),
    ]

    (sketch / "fail").touch()
    with pytest.raises(BuildError, match="the compile failed:\nerror: expected }"):
        compiler(sketch, build, "esp32:esp32:esp32")
