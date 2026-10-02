"""Imports every module's ORM mappings, so their tables register on the shared metadata.

Alembic (migrations/env.py) and the app import this. Add each new module's
`infrastructure.orm` here.
"""

from wiredex.catalog.infrastructure import orm as catalog_orm  # noqa: F401
from wiredex.files.infrastructure import orm as files_orm  # noqa: F401
from wiredex.firmware.infrastructure import orm as firmware_orm  # noqa: F401
from wiredex.history.infrastructure import orm as history_orm  # noqa: F401
from wiredex.identity.infrastructure import orm as identity_orm  # noqa: F401
from wiredex.inventory.infrastructure import orm as inventory_orm  # noqa: F401
from wiredex.projects.infrastructure import orm as projects_orm  # noqa: F401
