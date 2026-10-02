"""The search's own ids."""

from typing import NewType
from uuid import UUID

# The search declares its own WorkspaceId, as every module does: modules don't import each
# other's domain.
WorkspaceId = NewType("WorkspaceId", UUID)
