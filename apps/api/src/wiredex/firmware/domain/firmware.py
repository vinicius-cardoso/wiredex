"""A firmware: one line of code for a board, described once by its name, board target, framework
and description (ADR 0006).

What a firmware holds beyond that, its versions and the revisions it runs on, lives in their
own tables, so the entity owns only its details and its last change, which moves when any of
them changes (requirement 2.2).
"""

from dataclasses import dataclass
from datetime import datetime

from wiredex.firmware.domain.values import (
    BoardTarget,
    Description,
    FirmwareId,
    FirmwareName,
    Framework,
    WorkspaceId,
)


@dataclass(frozen=True, slots=True)
class FirmwareDetails:
    """Everything editable about a firmware, as one value.

    One object, so starting and revising take the same fields, and comparing it is how
    `revise` knows nothing changed (requirement 1.7).
    """

    name: FirmwareName
    target: BoardTarget
    framework: Framework
    description: Description | None = None


@dataclass(eq=False)
class Firmware:
    """The weather station's sketch, a Pico's blink: what its versions are snapshots of."""

    id: FirmwareId
    workspace_id: WorkspaceId
    name: FirmwareName
    target: BoardTarget
    framework: Framework
    description: Description | None
    created_at: datetime
    updated_at: datetime  # its last change, which orders the list (requirement 2.2)

    @classmethod
    def start(
        cls,
        firmware_id: FirmwareId,
        workspace_id: WorkspaceId,
        details: FirmwareDetails,
        now: datetime,
    ) -> Firmware:
        """A new firmware with no versions (requirement 1.1), created and last changed at the
        same instant."""
        return cls(
            id=firmware_id,
            workspace_id=workspace_id,
            name=details.name,
            target=details.target,
            framework=details.framework,
            description=details.description,
            created_at=now,
            updated_at=now,
        )

    @property
    def details(self) -> FirmwareDetails:
        return FirmwareDetails(self.name, self.target, self.framework, self.description)

    def revise(self, details: FirmwareDetails, now: datetime) -> bool:
        """Replaces the name, target, framework and description whole (requirement 1.7).

        Whether the name is free is the workspace's to say, before this. Returns whether
        anything changed, so an edit that changes nothing commits nothing and doesn't move the
        firmware up the list.
        """
        if self.details == details:
            return False
        self.name = details.name
        self.target = details.target
        self.framework = details.framework
        self.description = details.description
        self.updated_at = now
        return True

    def touch(self, now: datetime) -> None:
        """A link, a version or one of its files changed: the firmware's last change moves
        with it, so the list opens on what changed last (requirement 2.2)."""
        self.updated_at = now
