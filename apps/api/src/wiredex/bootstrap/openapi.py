"""Print the OpenAPI schema, for generating the TypeScript client without a running server.

uv run python -m wiredex.bootstrap.openapi > openapi.json
"""

import json
import sys
from typing import Any

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings

# The generated client describes the API contract, not a release. Pinning info.version
# keeps it byte-identical across releases, so a release PR (which only bumps the app
# version) never fails CI's "client is current" check. GET /api/version has the real one.
CONTRACT_VERSION = "unversioned"


def openapi_schema() -> dict[str, Any]:
    # Development settings: production hides the schema.
    schema = create_app(Settings(environment=Environment.DEVELOPMENT)).openapi()
    schema["info"]["version"] = CONTRACT_VERSION
    return schema


def main() -> None:
    sys.stdout.write(json.dumps(openapi_schema(), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
