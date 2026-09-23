import re
from importlib.metadata import version

SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:[-+].+)?$")


def test_distribution_version_is_semver() -> None:
    assert SEMVER.match(version("wiredex"))
