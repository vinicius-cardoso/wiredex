"""What the project list is narrowed by: a text in the name and tags the project must carry.

The in-memory fake filters with `matches`, and the SQL repository compiles the same two
conditions, so the integration tests can hold one against the other.
"""

from dataclasses import dataclass, field

from wiredex.projects.domain.project import Project
from wiredex.projects.domain.values import Tags


@dataclass(frozen=True, slots=True)
class ProjectFilter:
    """A text the name holds, ignoring case, and tags the project carries, all of them."""

    text: str | None = None
    tags: Tags = field(default_factory=Tags.none)

    def __post_init__(self) -> None:
        # A search box cleared to spaces asks for nothing, not for names holding a space.
        text = self.text.strip() if self.text is not None else ""
        object.__setattr__(self, "text", text or None)

    def matches(self, project: Project) -> bool:
        # lower(), not casefold(): what Postgres's ILIKE compares, so the fake and the SQL agree.
        if self.text is not None and self.text.lower() not in project.name.value.lower():
            return False
        return project.tags.include(self.tags)
