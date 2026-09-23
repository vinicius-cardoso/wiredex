import json

import pytest

import wiredex
from wiredex.bootstrap.openapi import CONTRACT_VERSION, main, openapi_schema


def test_schema_describes_the_system_endpoints() -> None:
    paths = openapi_schema()["paths"]

    assert {"/api/health", "/api/version"} <= paths.keys()


def test_main_prints_the_schema_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    printed = json.loads(capsys.readouterr().out)
    assert printed["info"]["title"] == "Wiredex API"


def test_schema_does_not_change_with_the_app_version(monkeypatch: pytest.MonkeyPatch) -> None:
    before = openapi_schema()
    monkeypatch.setattr(wiredex, "__version__", "9.9.9")

    after = openapi_schema()

    assert after == before
    assert after["info"]["version"] == CONTRACT_VERSION
