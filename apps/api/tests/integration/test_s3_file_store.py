"""The S3 file store against a real S3-compatible server (MinIO in a container).

What can only be checked here is what a bucket does over the wire: a written object reads
back byte for byte, `open` streams a multi-chunk object rather than holding it whole, `keys`
lists by prefix, deleting is quiet, and `get_object` on a missing key raises. It mirrors the
local store's tests, so both ends of the `FileStore` port behave the same, and it pins the
MinIO image tag the way the Postgres tests pin theirs.
"""

from collections.abc import AsyncIterator, Iterator

import pytest
from botocore.exceptions import ClientError
from testcontainers.community.minio import MinioContainer

from wiredex.files.domain.values import MediaType
from wiredex.files.infrastructure.stores import S3FileStore, s3_client

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

# A pinned MinIO release, like compose.yaml pins Postgres; never `latest`, so a rebuild years
# from now runs against the same server. MinIO went source-only in October 2025 and stopped
# publishing `minio/minio` to Docker Hub, so this is `alpine/minio`, which mirrors the same
# server binary of the last community release.
MINIO_IMAGE = "alpine/minio:RELEASE.2025-10-15T17-29-55Z"
BUCKET = "wiredex-files"
KEY = "workspaces/w1/sha256/" + "a" * 64


async def _drain(stream: AsyncIterator[bytes]) -> bytes:
    return b"".join([chunk async for chunk in stream])


@pytest.fixture(scope="module")
def store() -> Iterator[S3FileStore]:
    """A throwaway MinIO for the module, with the bucket the store writes to already made."""
    minio = MinioContainer(MINIO_IMAGE)
    # The alpine/minio image runs MinIO as a non-root user that can't write the root-owned
    # `/data` the module points the server at; a path under the world-writable `/tmp` it can.
    minio.with_command("server /tmp/minio --address :9000")
    with minio:
        config = minio.get_config()
        client = s3_client(
            endpoint=f"http://{config['endpoint']}",
            region="us-east-1",
            access_key=config["access_key"],
            secret_key=config["secret_key"],
        )
        client.create_bucket(Bucket=BUCKET)
        yield S3FileStore(BUCKET, client)


@pytest.fixture(autouse=True)
async def _clean(store: S3FileStore) -> None:
    """Each test starts from an empty bucket, so the module-scoped server can be reused."""
    async for key in store.keys(""):
        await store.delete(key)


# --- put and open -------------------------------------------------------------


async def test_a_written_object_reads_back_byte_for_byte(store: S3FileStore) -> None:
    await store.put(KEY, b"%PDF-1.7 hello", MediaType.PDF)
    assert await _drain(store.open(KEY)) == b"%PDF-1.7 hello"


async def test_a_large_object_streams_in_more_than_one_chunk(store: S3FileStore) -> None:
    # Requirement 3.5: the bytes are streamed, not held whole. Just over two chunks, so the
    # reader has to loop and every chunk but the last is a full 256 KiB.
    data = b"\x89PNG\r\n\x1a\n" + b"x" * (256 * 1024 * 2)
    await store.put(KEY, data, MediaType.PNG)
    chunks = [chunk async for chunk in store.open(KEY)]
    assert len(chunks) > 1
    assert all(len(chunk) <= 256 * 1024 for chunk in chunks)
    assert b"".join(chunks) == data


async def test_the_content_type_is_recorded_on_the_object(store: S3FileStore) -> None:
    # Unlike the local store, S3 keeps a content type; the API leans on it for the response.
    await store.put(KEY, b"%PDF-1.7", MediaType.PDF)
    head = store._client.head_object(Bucket=BUCKET, Key=KEY)
    assert head["ContentType"] == str(MediaType.PDF)


# --- keys ---------------------------------------------------------------------


async def test_keys_returns_only_objects_under_the_prefix(store: S3FileStore) -> None:
    mine = "workspaces/w1/sha256/" + "a" * 64
    also_mine = "workspaces/w1/sha256/" + "b" * 64
    another = "workspaces/w2/sha256/" + "c" * 64
    for key in (mine, also_mine, another):
        await store.put(key, b"%PDF-1.7", MediaType.PDF)

    found = {key async for key in store.keys("workspaces/w1/")}

    assert found == {mine, also_mine}


async def test_keys_of_an_empty_prefix_is_empty(store: S3FileStore) -> None:
    assert [key async for key in store.keys("workspaces/w1/")] == []


# --- delete -------------------------------------------------------------------


async def test_deleting_removes_the_object(store: S3FileStore) -> None:
    await store.put(KEY, b"%PDF-1.7", MediaType.PDF)
    await store.delete(KEY)
    assert [key async for key in store.keys("workspaces/w1/")] == []


async def test_deleting_a_missing_key_is_quiet(store: S3FileStore) -> None:
    # Removal stays idempotent, so a torn state resolves without an error.
    await store.delete(KEY)  # never written; must not raise


# --- a missing key ------------------------------------------------------------


async def test_opening_a_missing_key_raises(store: S3FileStore) -> None:
    # A read of a key that isn't there is a store error, not a quiet empty stream; the use
    # case turns it into a 404, the prune never opens what it's about to delete.
    with pytest.raises(ClientError):
        await _drain(store.open(KEY))
