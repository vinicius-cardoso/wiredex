from datetime import UTC, datetime, timedelta
from uuid import uuid7

from wiredex.identity.domain.model import Membership, User
from wiredex.identity.domain.values import Email, Name, PasswordHash, Role, UserId, WorkspaceId

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def a_user(expires_at: datetime | None = None) -> User:
    return User(
        id=UserId(uuid7()),
        email=Email("guest@example.com"),
        name=Name("Guest"),
        password_hash=PasswordHash("hash"),
        created_at=NOW,
        expires_at=expires_at,
    )


def test_users_without_expiry_stay_active() -> None:
    assert a_user().is_active(NOW + timedelta(days=3650))


def test_guests_stop_being_active_when_they_expire() -> None:
    guest = a_user(expires_at=NOW + timedelta(days=7))

    assert guest.is_active(NOW + timedelta(days=6))
    assert not guest.is_active(NOW + timedelta(days=7))


def test_only_owners_manage_a_workspace() -> None:
    def membership(role: Role) -> Membership:
        return Membership(UserId(uuid7()), WorkspaceId(uuid7()), role, NOW)

    assert membership(Role.OWNER).can_manage_workspace()
    assert not membership(Role.GUEST).can_manage_workspace()
