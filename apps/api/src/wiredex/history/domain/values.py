"""History's own ids."""

from typing import NewType
from uuid import UUID

# History declares its own WorkspaceId, as every module does: modules don't import each
# other's domain.
WorkspaceId = NewType("WorkspaceId", UUID)

# A change's id: the database numbers changes as it records them, so a higher one is newer.
ChangeId = NewType("ChangeId", int)
