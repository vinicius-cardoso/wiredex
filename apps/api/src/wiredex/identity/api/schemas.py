from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field

from wiredex.identity.application.sessions import CurrentUser, DeviceSession
from wiredex.identity.application.share_demo import SharedDemo
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


class ShareDemoRequest(BaseModel):
    email: str
    # How the app greets them; "Guest" when left out.
    name: str | None = None
    # How long the account works, from 1 to 90 days.
    days: int = Field(default=7, ge=1, le=90)


class SharedDemoResponse(BaseModel):
    """A guest's login, to pass on. The password is in this answer and nowhere else."""

    email: str
    name: str
    password: str
    expires_at: datetime

    @classmethod
    def from_shared(cls, shared: SharedDemo) -> Self:
        return cls(
            email=shared.email.value,
            name=shared.name.value,
            password=shared.password.value,
            expires_at=shared.expires_at,
        )


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


class ChangePasswordRequest(BaseModel):
    """Your current password, asked again, and the one to replace it with."""

    current_password: str
    new_password: str


class PasswordChangedResponse(BaseModel):
    """The password changed, and this many other devices were logged out by it."""

    revoked_sessions: int


type PasswordRefusalCodeName = Literal[
    "wrong_password", "weak_password", "same_password", "password_like_account"
]
type PasswordFieldName = Literal["current_password", "new_password"]


class PasswordRefusalResponse(BaseModel):
    """Why a password change was refused, as a code the web translates and the field it is
    about. Nothing changed."""

    code: PasswordRefusalCodeName
    field: PasswordFieldName
    message: str


class PasswordRefusalBody(BaseModel):
    detail: PasswordRefusalResponse
