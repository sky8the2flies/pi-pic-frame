"""Local cache for downloaded photos with disk-usage caps."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from shutil import disk_usage

from picture_frame.config import CacheConfig
from picture_frame.providers.base import PhotoAsset, PhotoProvider

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_FALLBACK_SIZE_HINT_BYTES = 10 * 1024 * 1024  # 10 MB


@dataclass(slots=True)
class CacheEntry:
    media_id: str
    filename: str
    relative_path: str
    size_bytes: int
    source: str
    last_seen_ts: float
    added_ts: float

    def absolute_path(self, cache_dir: Path) -> Path:
        return cache_dir / self.relative_path


class PhotoCache:
    """Filesystem cache with rolling eviction to stay under configured limits."""

    def __init__(self, config: CacheConfig) -> None:
        self._config = config
        self._config.directory.mkdir(parents=True, exist_ok=True)
        self._config.metadata_file.parent.mkdir(parents=True, exist_ok=True)
        self._entries = self._load_metadata()

    def entries(self) -> list[CacheEntry]:
        return list(self._entries.values())

    def image_paths(self) -> list[Path]:
        paths = [entry.absolute_path(self._config.directory) for entry in self._entries.values()]
        return [path for path in paths if path.exists()]

    def sync_assets(
        self, provider_name: str, assets: list[PhotoAsset], provider: PhotoProvider
    ) -> dict[str, int]:
        """Download new assets, keep existing ones, evict stale files."""
        now = time.time()
        seen_ids = {asset.media_id for asset in assets}
        downloaded = 0
        skipped = 0
        evicted = 0
        failed = 0

        for asset in assets:
            existing = self._entries.get(asset.media_id)
            if existing and existing.absolute_path(self._config.directory).exists():
                existing.last_seen_ts = now
                skipped += 1
                continue

            self._evict_until_target(asset.size_hint_bytes or _FALLBACK_SIZE_HINT_BYTES)
            target_path = self._build_asset_path(asset)
            try:
                tmp_path = self._download_to_temp(asset, provider)
            except Exception:
                logger.warning("Download failed for %s (%s)", asset.media_id, asset.filename, exc_info=True)
                failed += 1
                continue
            tmp_size = tmp_path.stat().st_size
            self._evict_until_target(tmp_size)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.replace(target_path)
            self._entries[asset.media_id] = CacheEntry(
                media_id=asset.media_id,
                filename=asset.filename,
                relative_path=target_path.name,
                size_bytes=tmp_size,
                source=provider_name,
                last_seen_ts=now,
                added_ts=now,
            )
            downloaded += 1

        for media_id, entry in list(self._entries.items()):
            if media_id in seen_ids:
                continue
            path = entry.absolute_path(self._config.directory)
            if path.exists():
                try:
                    path.unlink()
                    evicted += 1
                except OSError:
                    logger.warning("Failed to unlink stale cache file %s", path, exc_info=True)
                    continue
            del self._entries[media_id]

        self._save_metadata()
        return {
            "downloaded": downloaded,
            "skipped": skipped,
            "evicted": evicted,
            "failed": failed,
        }

    def _download_to_temp(self, asset: PhotoAsset, provider: PhotoProvider) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".tmp",
            delete=False,
            dir=str(self._config.directory),
        ) as handle:
            tmp_path = Path(handle.name)
        try:
            provider.download_asset(asset, tmp_path)
            return tmp_path
        except Exception:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    logger.debug("Could not remove temp file %s", tmp_path, exc_info=True)
            raise

    def _build_asset_path(self, asset: PhotoAsset) -> Path:
        suffix = Path(asset.filename).suffix or ".jpg"
        base = _SAFE_NAME.sub("_", Path(asset.filename).stem).strip("_") or "photo"
        return self._config.directory / f"{asset.media_id}_{base}{suffix.lower()}"

    def _evict_until_target(self, incoming_bytes: int) -> None:
        if incoming_bytes <= 0:
            return
        while self._violates_limits(incoming_bytes):
            victim = self._oldest_entry()
            if victim is None:
                break
            path = victim.absolute_path(self._config.directory)
            if path.exists():
                try:
                    path.unlink()
                except OSError:
                    logger.warning("Failed to evict cache file %s", path, exc_info=True)
                    break
            self._entries.pop(victim.media_id, None)

    def _violates_limits(self, incoming_bytes: int) -> bool:
        usage = disk_usage(self._config.directory)
        projected_used = usage.used + incoming_bytes
        projected_ratio = (projected_used / usage.total) * 100
        projected_free = usage.total - projected_used
        min_free_bytes = self._config.min_free_space_mb * 1024 * 1024
        return (
            projected_ratio > self._config.max_disk_usage_percent
            or projected_free < min_free_bytes
        )

    def _oldest_entry(self) -> CacheEntry | None:
        if not self._entries:
            return None
        return min(self._entries.values(), key=lambda item: item.last_seen_ts)

    def _load_metadata(self) -> dict[str, CacheEntry]:
        path = self._config.metadata_file
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Discarding corrupt cache metadata at %s", path, exc_info=True)
            return {}
        entries: dict[str, CacheEntry] = {}
        for item in payload.get("entries", []):
            relative_path = item.get("relative_path")
            if not relative_path:
                # Backward compat: derive relative path from legacy absolute file_path.
                legacy = item.get("file_path", "")
                relative_path = Path(legacy).name if legacy else ""
            if not relative_path:
                continue
            try:
                entry = CacheEntry(
                    media_id=item["media_id"],
                    filename=item["filename"],
                    relative_path=relative_path,
                    size_bytes=int(item["size_bytes"]),
                    source=item["source"],
                    last_seen_ts=float(item["last_seen_ts"]),
                    added_ts=float(item["added_ts"]),
                )
            except (KeyError, TypeError, ValueError):
                logger.warning("Skipping malformed cache metadata row: %r", item)
                continue
            entries[entry.media_id] = entry
        return entries

    def _save_metadata(self) -> None:
        payload = {
            "entries": [
                {
                    "media_id": entry.media_id,
                    "filename": entry.filename,
                    "relative_path": entry.relative_path,
                    "size_bytes": entry.size_bytes,
                    "source": entry.source,
                    "last_seen_ts": entry.last_seen_ts,
                    "added_ts": entry.added_ts,
                }
                for entry in sorted(self._entries.values(), key=lambda row: row.added_ts)
            ]
        }
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(self._config.metadata_file.parent),
        ) as handle:
            json.dump(payload, handle, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
            tmp_path = Path(handle.name)
        tmp_path.replace(self._config.metadata_file)
