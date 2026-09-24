from datetime import UTC, datetime, timedelta
from uuid import uuid7

from wiredex.identity.domain.session import ABSOLUTE_LIFETIME, SLIDING_LIFETIME, Session
from wiredex.identity.domain.values import SessionId, SessionTokenHash, UserId

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)


def a_session() -> Session:
    return Session.start(
        SessionId(uuid7()), UserId(uuid7()), SessionTokenHash("h"), "Firefox on Linux", NOW
    )


def test_a_new_session_lasts_the_sliding_lifetime() -> None:
    session = a_session()

    assert session.is_valid(NOW + SLIDING_LIFETIME - timedelta(seconds=1))
    assert not session.is_valid(NOW + SLIDING_LIFETIME)


def test_use_renews_it_but_not_on_every_request() -> None:
    session = a_session()

    assert not session.touch(NOW + timedelta(minutes=4))  # too soon to write
    assert session.touch(NOW + timedelta(days=20))
    assert session.expires_at == NOW + timedelta(days=20) + SLIDING_LIFETIME


def test_renewal_never_passes_the_absolute_lifetime() -> None:
    session = a_session()

    session.touch(NOW + timedelta(days=80))

    assert session.expires_at == NOW + ABSOLUTE_LIFETIME


def test_long_device_names_are_cut() -> None:
    long = Session.start(SessionId(uuid7()), UserId(uuid7()), SessionTokenHash("h"), "x" * 500, NOW)

    assert len(long.device) == 120
