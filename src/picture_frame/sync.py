"""Coordinates provider fetches with the on-disk cache."""

from __future__ import annotations

import logging

from picture_frame.cache import PhotoCache
from picture_frame.config import AppConfig
from picture_frame.providers.base import PhotoAsset
from picture_frame.providers.immich import ImmichProvider, ImmichSettings

logger = logging.getLogger(__name__)


class SyncEngine:
    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._cache = PhotoCache(config.cache)
        self._provider = self._build_provider()

    @property
    def cache(self) -> PhotoCache:
        return self._cache

    @property
    def provider(self) -> ImmichProvider:
        return self._provider

    def authenticate(self) -> None:
        self._provider.authenticate()

    def list_assets(self, album_id: str) -> list[PhotoAsset]:
        return self._provider.list_assets(album_id)

    def list_albums(self) -> list[dict[str, object]]:
        return self._provider.list_albums()

    def sync_once(self) -> dict[str, int]:
        """Fetch configured albums and reconcile the cache."""
        self.authenticate()
        all_assets: list[PhotoAsset] = []
        for album_id in self._config.immich.albums:
            logger.info("Syncing Immich album %s", album_id)
            all_assets.extend(self._provider.list_assets(album_id))

        unique_assets = {asset.media_id: asset for asset in all_assets}
        results = self._cache.sync_assets(
            provider_name="immich",
            assets=list(unique_assets.values()),
            provider=self._provider,
        )
        logger.info("Sync complete: %s", results)
        return results

    def rebind_provider(self) -> None:
        """Rebuild the provider after credentials or base URL change."""
        self._provider = self._build_provider()

    def _build_provider(self) -> ImmichProvider:
        return ImmichProvider(
            ImmichSettings(
                base_url=self._config.immich.base_url,
                api_key=self._config.immich.api_key,
                request_timeout_seconds=self._config.immich.request_timeout_seconds,
            )
        )
