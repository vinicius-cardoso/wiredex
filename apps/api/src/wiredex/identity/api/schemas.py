from datetime import datetime
from typing import Self
from uuid import UUID

from pydantic import BaseModel

from wiredex.identity.application.sessions import CurrentUser, DeviceSession
from wiredex.identity.domain.model import User


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str
    # When a guest's access ends; null for the owner, whose account never expires.
    expires_at: datetime | None

    @classmethod
    def from_user(cls, user: User) -> Self:
        return cls(
            id=user.id, email=user.email.value, name=user.name.value, expires_at=user.expires_at
        )


class CurrentUserResponse(UserResponse):
    """The account, plus the workspace this session acts in (ADR 0007)."""

    workspace_id: UUID

    @classmethod
    def from_current(cls, current: CurrentUser) -> Self:
        account = UserResponse.from_user(current.user)
        return cls(**account.model_dump(), workspace_id=current.workspace_id)


class TokenResponse(BaseModel):
    token: str
    user: UserResponse


class SessionResponse(BaseModel):
    """A logged-in device. `current` marks the one making this request."""

    id: UUID
    device: str
    created_at: datetime
    last_seen_at: datetime
    current: bool

    @classmethod
    def from_device(cls, device: DeviceSession) -> Self:
        session = device.session
        return cls(
            id=session.id,
            device=session.device,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            current=device.is_current,
        )
