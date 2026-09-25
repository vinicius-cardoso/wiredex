"""Imports every module's ORM mappings, so their tables register on the shared metadata.

Alembic (migrations/env.py) and the app import this. Add each new module's
`infrastructure.orm` here.
"""

from wiredex.catalog.infrastructure import orm as catalog_orm  # noqa: F401
from wiredex.files.infrastructure import orm as files_orm  # noqa: F401
from wiredex.identity.infrastructure import orm as identity_orm  # noqa: F401
