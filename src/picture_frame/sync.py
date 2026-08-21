"""Coordinates provider fetches with the on-disk cache."""

from __future__ import annotations

import logging

from picture_frame.cache import PhotoCache
from picture_frame.config import AppConfig
from picture_frame.providers.base import PhotoAsset
from picture_frame.providers.immich import ImmichProvider, ImmichSettings

logger = logging.getLogger(__name__)


def select_rotation_window(asset_ids: list[str], start: int, window_size: int) -> list[str]:
    """Select a wrapping window from an ordered asset ID list."""
    if not asset_ids or window_size <= 0:
        return []
    start %= len(asset_ids)
    ordered = asset_ids[start:] + asset_ids[:start]
    return ordered[: min(window_size, len(asset_ids))]


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
        ordered_ids = sorted(unique_assets)
        ordered_assets = [unique_assets[media_id] for media_id in ordered_ids]

        rotation = self._cache.get_rotation_state()
        total_assets = len(ordered_assets)
        if total_assets:
            cache_entries = self._cache.entries()
            cached_count = len(cache_entries)
            window_size = min(cached_count or total_assets, total_assets)
            start = rotation["next_index"] if rotation["total_assets"] == total_assets else 0
            selected_ids = select_rotation_window(ordered_ids, start, window_size)
            selected_assets = [unique_assets[media_id] for media_id in selected_ids]
            cached_ids = {
                entry.media_id for entry in cache_entries if getattr(entry, "media_id", None) is not None
            }
            selected_assets.sort(key=lambda asset: asset.media_id not in cached_ids)
            next_index = (start + window_size) % total_assets
        else:
            selected_assets = []
            next_index = 0

        results = self._cache.sync_assets(
            provider_name="immich",
            assets=selected_assets,
            provider=self._provider,
        )
        self._cache.set_rotation_state(total_assets=total_assets, next_index=next_index)
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
