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

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

from wiredex.files.domain.values import MediaType

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
