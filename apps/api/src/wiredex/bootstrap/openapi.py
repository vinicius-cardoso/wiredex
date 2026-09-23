"""Print the OpenAPI schema, for generating the TypeScript client without a running server.

uv run python -m wiredex.bootstrap.openapi > openapi.json
"""

import json
import sys
from typing import Any

from wiredex.bootstrap.app import create_app
from wiredex.bootstrap.settings import Environment, Settings


def openapi_schema() -> dict[str, Any]:
    # Development settings: production hides the schema.
    return create_app(Settings(environment=Environment.DEVELOPMENT)).openapi()


def main() -> None:
    sys.stdout.write(json.dumps(openapi_schema(), indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
