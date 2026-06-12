"""Local filesystem storage — for development and small self-hosted setups."""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class LocalStorage:
    def __init__(self, base_dir: str):
        self._base = Path(base_dir)
        self._base.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        # Keys are server-generated, but resolve defensively anyway
        path = (self._base / key).resolve()
        if not path.is_relative_to(self._base.resolve()):
            raise ValueError(f"Invalid storage key: {key}")
        return path

    async def put(self, key: str, data: bytes, media_type: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)

    async def get(self, key: str) -> bytes | None:
        path = self._path(key)
        if not path.is_file():
            return None
        return await asyncio.to_thread(path.read_bytes)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_file():
            await asyncio.to_thread(path.unlink)

    async def signed_url(self, key: str, ttl_seconds: int = 3600) -> str | None:
        return None  # callers stream through the API

    async def close(self) -> None:
        pass
