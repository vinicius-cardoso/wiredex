"""File-store adapters: where an object's bytes actually live (design §3, Adapters).

`LocalFileStore` keeps the bytes under a folder, the default in development
(`apps/api/.files/`, gitignored) and in the e2e run. It is the counterpart of the S3 store
used in production: both satisfy the `FileStore` port, so a use case never knows which one
it holds. Blocking file work runs in a worker thread, so the event loop is never held while
a disk read or write is in flight (requirement 7.3), the same rule the S3 store follows for
its network calls.

A key is `StoredFile.object_key`, `workspaces/<workspace_id>/sha256/<hex>`; it maps to a
path of the same shape under the root, so the folder mirrors the bucket a production
deployment would use.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from wiredex.files.domain.values import MediaType

if TYPE_CHECKING:
    from types_boto3_s3 import S3Client
    from types_boto3_s3.type_defs import ListObjectsV2OutputTypeDef

# 256 KiB a read, so a 25 MiB PDF is streamed in a hundred-odd chunks rather than held whole.
_CHUNK_SIZE = 256 * 1024


class LocalFileStore:
    """The bytes on the local filesystem, one file per object key, under a single root folder.

    A write is atomic: the bytes go to a temporary name in the same directory and are then
    renamed onto the final path, so a reader never sees a half-written file and a crash
    mid-write leaves only a stray temporary the next write overwrites. `media_type` is
    ignored here, since the filesystem carries no content type; the S3 store records it.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    async def put(self, key: str, data: bytes, media_type: MediaType) -> None:  # noqa: ARG002
        """Write the object atomically. Idempotent: the same key and bytes may be written again.

        `media_type` is part of the `FileStore` contract, which the S3 store records on the
        object; the filesystem carries no content type, so it is unused here.
        """
        await asyncio.to_thread(self._write, key, data)

    async def open(self, key: str) -> AsyncIterator[bytes]:
        """The object's bytes, streamed in 256 KiB chunks so a large file never sits in memory
        whole (requirement 3.5). Not called with `await`: the call returns the iterator."""
        path = self._path(key)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(handle.read, _CHUNK_SIZE):
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        """Delete the object. A key that isn't there is fine, so removal stays idempotent."""
        await asyncio.to_thread(self._path(key).unlink, missing_ok=True)

    async def keys(self, prefix: str) -> AsyncIterator[str]:
        """Every object key under the prefix, for the prune to find objects no row names.

        The keys are gathered in a worker thread, then yielded: walking the tree touches the
        disk, but a store this size holds few enough keys to list in one pass.
        """
        for key in await asyncio.to_thread(self._keys_under, prefix):
            yield key

    async def modified_at(self, key: str) -> datetime | None:
        """The file's modification time, or None when it isn't there."""
        return await asyncio.to_thread(self._modified_at, key)

    def _modified_at(self, key: str) -> datetime | None:
        try:
            return datetime.fromtimestamp(self._path(key).stat().st_mtime, UTC)
        except FileNotFoundError:
            return None

    def _path(self, key: str) -> Path:
        return self._root / key

    def _write(self, key: str, data: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A temporary in the same directory, so the rename onto the final path is atomic
        # (both sides live on one filesystem); a torn write leaves only this stray behind.
        temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        temporary.write_bytes(data)
        temporary.replace(path)

    def _keys_under(self, prefix: str) -> list[str]:
        # Keys use forward slashes whatever the platform's separator is, so the store speaks
        # the same key shape the S3 store does; matching is a plain prefix test on that.
        root = self._root
        keys = [
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.name.endswith(".tmp")
        ]
        return [key for key in keys if key.startswith(prefix)]


def s3_client(endpoint: str, region: str, access_key: str, secret_key: str) -> S3Client:
    """A boto3 S3 client for an S3-compatible endpoint (OCI Object Storage in production).

    Path-style addressing (`endpoint/bucket/key`, not `bucket.endpoint/key`), because OCI's
    S3-compatible API doesn't serve virtual-hosted buckets. The checksum settings are the
    point of this factory: recent boto3 attaches a request checksum and validates a response
    one by default, and OCI rejects the header, so both are turned down to `when_required`
    (design §3, Adapters).
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(
            s3={"addressing_style": "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
        ),
    )


class S3FileStore:
    """The bytes in an S3-compatible bucket, one object per key, the store used in production.

    Every boto3 call is synchronous and does network I/O, so each one runs in a worker thread
    (`asyncio.to_thread`); the event loop is never held while a request is in flight
    (requirement 7.3), the same rule `LocalFileStore` follows for the disk. `open` streams the
    response body in 256 KiB chunks, so a 25 MiB PDF never sits in the container's memory
    whole (requirement 3.5).
    """

    def __init__(self, bucket: str, client: S3Client) -> None:
        self._bucket = bucket
        self._client = client

    async def put(self, key: str, data: bytes, media_type: MediaType) -> None:
        """Write the object with its content type. Idempotent: the same key and bytes overwrite."""
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=str(media_type),
        )

    async def open(self, key: str) -> AsyncIterator[bytes]:
        """The object's bytes, streamed in 256 KiB chunks (requirement 3.5). Not called with
        `await`: the call returns the iterator, like `LocalFileStore.open`."""
        response = await asyncio.to_thread(self._client.get_object, Bucket=self._bucket, Key=key)
        body = response["Body"]
        try:
            while chunk := await asyncio.to_thread(body.read, _CHUNK_SIZE):
                yield chunk
        finally:
            await asyncio.to_thread(body.close)

    async def delete(self, key: str) -> None:
        """Delete the object. A key that isn't there is fine: S3 delete is already idempotent,
        so nothing to catch, and removal stays quiet."""
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def modified_at(self, key: str) -> datetime | None:
        """The object's `LastModified`, from a HEAD request, or None when it isn't there."""
        try:
            head = await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return None
            raise
        return head["LastModified"]

    async def keys(self, prefix: str) -> AsyncIterator[str]:
        """Every object key under the prefix, for the prune to find objects no row names.

        Listing is paginated by S3; each page is fetched in a worker thread, then its keys are
        yielded before the next page is asked for.
        """
        token: str | None = None
        while True:
            page = await asyncio.to_thread(self._list_page, prefix, token)
            for item in page.get("Contents", []):
                if (found := item.get("Key")) is not None:
                    yield found
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated"):
                return

    def _list_page(self, prefix: str, token: str | None) -> ListObjectsV2OutputTypeDef:
        # A continuation token can't be passed as None, so the first page omits it.
        if token is None:
            return self._client.list_objects_v2(Bucket=self._bucket, Prefix=prefix)
        return self._client.list_objects_v2(
            Bucket=self._bucket, Prefix=prefix, ContinuationToken=token
        )
