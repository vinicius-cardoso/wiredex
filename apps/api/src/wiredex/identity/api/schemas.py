from typing import Self
from uuid import UUID

from pydantic import BaseModel

from wiredex.identity.domain.model import User


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    id: UUID
    email: str
    name: str

    @classmethod
    def from_user(cls, user: User) -> Self:
        return cls(id=user.id, email=user.email.value, name=user.name.value)


class TokenResponse(BaseModel):
    token: str
    user: UserResponse
