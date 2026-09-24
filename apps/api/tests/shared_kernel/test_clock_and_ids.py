from datetime import UTC

from wiredex.shared_kernel.infrastructure.clock import SystemClock
from wiredex.shared_kernel.infrastructure.ids import Uuid7Generator


def test_the_clock_is_timezone_aware_utc() -> None:
    assert SystemClock().now().tzinfo is UTC


def test_ids_are_uuid7_and_sort_in_creation_order() -> None:
    generator = Uuid7Generator()

    ids = [generator.new_id() for _ in range(100)]

    assert {identifier.version for identifier in ids} == {7}
    assert ids == sorted(ids)
