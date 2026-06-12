"""Attachment storage providers."""

from magpie.storage.base import StorageProvider
from magpie.storage.local import LocalStorage
from magpie.storage.s3 import S3Storage

__all__ = ["StorageProvider", "LocalStorage", "S3Storage", "create_storage"]


def create_storage(settings) -> StorageProvider | None:
    """Build the configured storage provider, or None if storage is unset."""
    if settings.storage_provider == "local":
        return LocalStorage(settings.storage_dir)
    if settings.storage_provider == "s3":
        return S3Storage(
            bucket=settings.storage_bucket,
            endpoint=settings.storage_endpoint,
            access_key_id=settings.storage_access_key_id,
            secret_access_key=settings.storage_secret_access_key,
            region=settings.storage_region,
        )
    return None
