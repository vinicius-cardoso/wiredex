"""The local file store keeps bytes under a folder, the store used in development and e2e.

These exercise the `FileStore` contract the use cases lean on: a written object reads back
byte for byte, `open` streams a large object in chunks rather than whole, `keys` finds
objects by prefix, and deleting a key that isn't there is quiet. Each test uses `tmp_path`,
so the root is a throwaway folder pytest cleans up.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from wiredex.files.domain.values import MediaType
from wiredex.files.infrastructure.stores import LocalFileStore

pytestmark = pytest.mark.anyio

KEY = "workspaces/w1/sha256/" + "a" * 64


async def _drain(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


# --- put and open -------------------------------------------------------------


async def test_a_written_object_reads_back_byte_for_byte(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    await store.put(KEY, b"%PDF-1.7 hello", MediaType.PDF)
    assert await _drain(store.open(KEY)) == b"%PDF-1.7 hello"


async def test_a_large_object_streams_in_more_than_one_chunk(tmp_path: Path) -> None:
    # Requirement 3.5: the bytes are streamed, not held whole. Just over two chunks, so the
    # reader has to loop and every chunk but the last is a full 256 KiB.
    store = LocalFileStore(tmp_path)
    data = b"\x89PNG\r\n\x1a\n" + b"x" * (256 * 1024 * 2)
    await store.put(KEY, data, MediaType.PNG)
    chunks = [chunk async for chunk in store.open(KEY)]
    assert len(chunks) > 1
    assert all(len(chunk) <= 256 * 1024 for chunk in chunks)
    assert b"".join(chunks) == data


async def test_the_key_maps_to_a_path_of_the_same_shape(tmp_path: Path) -> None:
    # The folder mirrors the bucket a production deploy would use: the key becomes the path.
    store = LocalFileStore(tmp_path)
    await store.put(KEY, b"%PDF-1.7", MediaType.PDF)
    assert (tmp_path / KEY).is_file()


async def test_writing_the_same_key_again_overwrites_and_leaves_no_temporary(
    tmp_path: Path,
) -> None:
    # Idempotent: a retry of the same upload writes the same object and no stray temporary.
    store = LocalFileStore(tmp_path)
    await store.put(KEY, b"%PDF-1.7 one", MediaType.PDF)
    await store.put(KEY, b"%PDF-1.7 two", MediaType.PDF)
    assert await _drain(store.open(KEY)) == b"%PDF-1.7 two"
    assert list((tmp_path / KEY).parent.glob("*.tmp")) == []


# --- keys ---------------------------------------------------------------------


async def test_keys_returns_only_objects_under_the_prefix(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    mine = "workspaces/w1/sha256/" + "a" * 64
    also_mine = "workspaces/w1/sha256/" + "b" * 64
    another = "workspaces/w2/sha256/" + "c" * 64
    for key in (mine, also_mine, another):
        await store.put(key, b"%PDF-1.7", MediaType.PDF)

    found = {key async for key in store.keys("workspaces/w1/")}

    assert found == {mine, also_mine}


async def test_keys_of_an_empty_store_is_empty(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    assert [key async for key in store.keys("workspaces/w1/")] == []


# --- delete -------------------------------------------------------------------


async def test_deleting_removes_the_object(tmp_path: Path) -> None:
    store = LocalFileStore(tmp_path)
    await store.put(KEY, b"%PDF-1.7", MediaType.PDF)
    await store.delete(KEY)
    assert [key async for key in store.keys("workspaces/w1/")] == []


async def test_deleting_a_missing_key_is_quiet(tmp_path: Path) -> None:
    # Requirement: removal stays idempotent, so a torn state resolves without an error.
    store = LocalFileStore(tmp_path)
    await store.delete(KEY)  # never written; must not raise


async def test_an_object_reports_when_it_was_written(tmp_path: Path) -> None:
    # The prune's grace period reads this: a young object may be an upload in flight.
    store = LocalFileStore(tmp_path)
    before = datetime.now(UTC) - timedelta(seconds=1)
    await store.put(KEY, b"%PDF-1.7", MediaType.PDF)

    written = await store.modified_at(KEY)

    assert written is not None
    assert before <= written <= datetime.now(UTC) + timedelta(seconds=1)
    assert await store.modified_at("workspaces/w1/sha256/missing") is None
