from datetime import UTC, datetime, timedelta

from wiredex.identity.infrastructure.throttle import InMemoryLoginThrottle

NOW = datetime(2026, 9, 24, 12, tzinfo=UTC)

ACCOUNT, IP = "account:owner@example.com", "ip:203.0.113.7"


def test_five_failures_block_the_account_for_fifteen_minutes() -> None:
    throttle = InMemoryLoginThrottle()
    for minute in range(5):
        throttle.record_failure([ACCOUNT], NOW + timedelta(minutes=minute))

    assert throttle.is_blocked([ACCOUNT], NOW + timedelta(minutes=5))
    # 15 minutes after the first failure, it no longer counts.
    assert not throttle.is_blocked([ACCOUNT], NOW + timedelta(minutes=15))


def test_an_ip_gets_more_room_than_an_account() -> None:
    throttle = InMemoryLoginThrottle()
    throttle.record_failure([IP] * 19, NOW)

    assert not throttle.is_blocked([IP], NOW)
    throttle.record_failure([IP], NOW)
    assert throttle.is_blocked([IP], NOW)


def test_clearing_forgets_a_key() -> None:
    throttle = InMemoryLoginThrottle()
    throttle.record_failure([ACCOUNT] * 5, NOW)

    throttle.clear(ACCOUNT)

    assert not throttle.is_blocked([ACCOUNT], NOW)
