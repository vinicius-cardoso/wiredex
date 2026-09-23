import json

import pytest

from wiredex.bootstrap.openapi import main, openapi_schema


def test_schema_describes_the_system_endpoints() -> None:
    paths = openapi_schema()["paths"]

    assert {"/api/health", "/api/version"} <= paths.keys()


def test_main_prints_the_schema_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    main()

    printed = json.loads(capsys.readouterr().out)
    assert printed["info"]["title"] == "Wiredex API"
