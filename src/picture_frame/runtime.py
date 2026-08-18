"""Shared runtime state and background workers."""

from __future__ import annotations

import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from picture_frame.config import ALLOWED_DISPLAY_MODES, AppConfig, save_config
from picture_frame.providers.immich import ImmichError
from picture_frame.sync import SyncEngine

logger = logging.getLogger(__name__)

_MIN_SYNC_INTERVAL_SECONDS = 60
_SYNC_SLEEP_TICK_SECONDS = 1.0


@dataclass(slots=True)
class RuntimeState:
    paused: bool = False
    stop: bool = False
    images: list[Path] = field(default_factory=list)
    current_index: int = 0
    last_sync_stats: dict[str, int] = field(default_factory=dict)
    last_sync_ts: float | None = None
    last_error: str | None = None
    _next_delta: int = 0

    def set_images(self, images: list[Path]) -> None:
        self.images = images
        if self.images:
            self.current_index = self.current_index % len(self.images)
        else:
            self.current_index = 0

    def request_next(self) -> None:
        self._next_delta += 1

    def request_previous(self) -> None:
        self._next_delta -= 1

    def consume_delta(self) -> int:
        delta = self._next_delta
        self._next_delta = 0
        return delta


class PictureFrameRuntime:
    """Coordinates configuration, sync engine, and slideshow state."""

    def __init__(self, config: AppConfig, config_path: Path | None = None) -> None:
        self.config = config
        self.config_path = config_path
        self.sync = SyncEngine(config)
        self.state = RuntimeState()
        self._lock = threading.RLock()
        self._sync_thread: threading.Thread | None = None

    def refresh_images(self) -> list[Path]:
        with self._lock:
            images = sorted(self.sync.cache.image_paths())
            self.state.set_images(images)
            return images

    def sync_now(self) -> dict[str, int]:
        try:
            stats = self.sync.sync_once()
        except Exception as exc:
            self.state.last_error = str(exc)
            logger.exception("Sync failed")
            raise
        with self._lock:
            self.state.last_sync_stats = stats
            self.state.last_sync_ts = time.time()
            self.state.last_error = None
            self.refresh_images()
        return stats

    def immich_configured(self) -> bool:
        return bool(self.config.immich.base_url and self.config.immich.api_key)

    def set_immich_credentials(self, base_url: str, api_key: str) -> None:
        base_url = base_url.strip().rstrip("/")
        api_key = api_key.strip()
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")

        with self._lock:
            self.config.immich.base_url = base_url
            self.config.immich.api_key = api_key
            self.sync.rebind_provider()
            self._persist_config()

        self.sync.authenticate()

    def list_available_albums(self) -> list[dict[str, object]]:
        self.sync.authenticate()
        return self.sync.list_albums()

    def update_albums(self, albums: list[str], sync_now: bool = False) -> dict[str, object]:
        normalized = [album.strip() for album in albums if album and album.strip()]
        if not normalized:
            raise ValueError("albums must contain at least one album id")

        self.sync.authenticate()
        for album_id in normalized:
            try:
                self.sync.list_assets(album_id)
            except ImmichError as exc:
                raise ValueError(f"album {album_id} could not be read: {exc}") from exc

        with self._lock:
            self.config.immich.albums = normalized
            self._persist_config()

        response: dict[str, object] = {"albums": normalized}
        if sync_now:
            response["sync"] = self.sync_now()
        return response

    def update_sync_settings(self, interval_minutes: int) -> dict[str, int]:
        if interval_minutes < 1 or interval_minutes > 1440:
            raise ValueError("interval_minutes must be between 1 and 1440")
        with self._lock:
            self.config.sync.interval_minutes = int(interval_minutes)
            self._persist_config()
        return {"interval_minutes": self.config.sync.interval_minutes}

    def update_cache_settings(
        self,
        max_disk_usage_percent: int | None = None,
        min_free_space_mb: int | None = None,
    ) -> dict[str, int]:
        with self._lock:
            cache_cfg = self.config.cache
            if max_disk_usage_percent is not None:
                if max_disk_usage_percent < 10 or max_disk_usage_percent > 99:
                    raise ValueError("max_disk_usage_percent must be between 10 and 99")
                cache_cfg.max_disk_usage_percent = int(max_disk_usage_percent)
            if min_free_space_mb is not None:
                if min_free_space_mb < 0:
                    raise ValueError("min_free_space_mb must be >= 0")
                cache_cfg.min_free_space_mb = int(min_free_space_mb)
            self._persist_config()
            return {
                "max_disk_usage_percent": cache_cfg.max_disk_usage_percent,
                "min_free_space_mb": cache_cfg.min_free_space_mb,
            }

    def cache_stats(self) -> dict[str, object]:
        """Return current cache size and disk usage for the cache directory."""
        cache_cfg = self.config.cache
        entries = self.sync.cache.entries()
        cached_bytes = sum(entry.size_bytes for entry in entries)
        try:
            usage = shutil.disk_usage(cache_cfg.directory)
            disk = {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "used_percent": (usage.used / usage.total) * 100 if usage.total else 0,
            }
        except OSError:
            disk = {"total_bytes": 0, "used_bytes": 0, "free_bytes": 0, "used_percent": 0}
        return {
            "cached_bytes": cached_bytes,
            "cached_files": len(entries),
            "directory": str(cache_cfg.directory),
            "max_disk_usage_percent": cache_cfg.max_disk_usage_percent,
            "min_free_space_mb": cache_cfg.min_free_space_mb,
            "disk": disk,
        }

    def update_display_settings(
        self,
        slide_seconds: int | None = None,
        transition_seconds: float | None = None,
        mode: str | None = None,
    ) -> dict[str, object]:
        with self._lock:
            display = self.config.display
            if slide_seconds is not None:
                if slide_seconds < 1 or slide_seconds > 3600:
                    raise ValueError("slide_seconds must be between 1 and 3600")
                display.slide_seconds = int(slide_seconds)
            if transition_seconds is not None:
                if transition_seconds < 0 or transition_seconds > 10:
                    raise ValueError("transition_seconds must be between 0 and 10")
                display.transition_seconds = float(transition_seconds)
            if mode is not None:
                if mode not in ALLOWED_DISPLAY_MODES:
                    raise ValueError(
                        f"mode must be one of {sorted(ALLOWED_DISPLAY_MODES)}"
                    )
                display.mode = mode
            self._persist_config()
            return {
                "slide_seconds": display.slide_seconds,
                "transition_seconds": display.transition_seconds,
                "mode": display.mode,
            }

    def start_sync_loop(self) -> None:
        if self._sync_thread and self._sync_thread.is_alive():
            return
        self._sync_thread = threading.Thread(
            target=self._sync_worker,
            name="picture-frame-sync",
            daemon=True,
        )
        self._sync_thread.start()

    def request_stop(self) -> None:
        """Signal all workers to exit at the next check."""
        logger.info("Stop requested")
        self.state.stop = True

    def _sync_worker(self) -> None:
        while not self.state.stop:
            try:
                if self.immich_configured() and self.config.immich.albums:
                    self.sync_now()
            except Exception:
                # Already logged inside sync_now; keep the loop alive.
                pass
            sync_finished_at = time.time()
            # Re-read the interval on every tick so runtime UI changes take
            # effect without waiting for the current cycle to end.
            while not self.state.stop:
                interval_s = max(
                    _MIN_SYNC_INTERVAL_SECONDS,
                    self.config.sync.interval_minutes * 60,
                )
                if time.time() - sync_finished_at >= interval_s:
                    break
                time.sleep(_SYNC_SLEEP_TICK_SECONDS)

    def _persist_config(self) -> None:
        if self.config_path is not None:
            try:
                save_config(self.config_path, self.config)
            except OSError:
                logger.exception("Failed to persist config to %s", self.config_path)
