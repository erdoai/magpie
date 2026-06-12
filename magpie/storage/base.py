"""Storage provider protocol for attachments."""

from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageProvider(Protocol):
    """Stores attachment bytes by key.

    Keys are opaque paths like ``org/<org_id>/entry/<entry_id>/<attachment_id>``.
    """

    async def put(self, key: str, data: bytes, media_type: str) -> None: ...

    async def get(self, key: str) -> bytes | None: ...

    async def delete(self, key: str) -> None: ...

    async def signed_url(self, key: str, ttl_seconds: int = 3600) -> str | None:
        """Time-limited direct download URL, or None if the provider can't
        produce one (callers fall back to streaming through the API)."""
        ...

    async def close(self) -> None: ...
