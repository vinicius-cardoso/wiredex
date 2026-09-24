"""Imports every module's ORM mappings, so their tables register on the shared metadata.

Alembic (migrations/env.py) and the app import this. Add each new module's
`infrastructure.orm` here.
"""

from wiredex.identity.infrastructure import orm as identity_orm  # noqa: F401
