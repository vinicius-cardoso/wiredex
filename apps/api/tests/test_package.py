import re

import wiredex

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def test_version_is_semver() -> None:
    assert SEMVER.match(wiredex.__version__)
