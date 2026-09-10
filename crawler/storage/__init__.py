from crawler.storage.base import BaseStorageBackend
from crawler.storage.local import LocalStorageBackend
from crawler.storage.google import GoogleCloudStorageBackend

__all__ = ["BaseStorageBackend", "LocalStorageBackend", "GoogleCloudStorageBackend"]
