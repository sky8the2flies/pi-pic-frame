"""Typed configuration objects loaded from a TOML file."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomli_w

ALLOWED_DISPLAY_MODES = frozenset({"crop", "fit", "fit_blur"})
DEFAULT_SLIDE_SECONDS = 20
DEFAULT_TRANSITION_SECONDS = 0.8
DEFAULT_MODE = "fit_blur"


@dataclass(slots=True)
class ImmichConfig:
    base_url: str = "http://localhost:2283"
    api_key: str = ""
    albums: list[str] = field(default_factory=list)
    request_timeout_seconds: float = 30.0


@dataclass(slots=True)
class CacheConfig:
    directory: Path
    metadata_file: Path
    max_disk_usage_percent: int = 80
    min_free_space_mb: int = 512


@dataclass(slots=True)
class DisplayConfig:
    slide_seconds: int = DEFAULT_SLIDE_SECONDS
    transition_seconds: float = DEFAULT_TRANSITION_SECONDS
    mode: str = DEFAULT_MODE


@dataclass(slots=True)
class SyncConfig:
    interval_minutes: int = 30


@dataclass(slots=True)
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    # If set, all mutating endpoints require Authorization: Bearer <auth_token>.
    auth_token: str = ""


@dataclass(slots=True)
class AppConfig:
    immich: ImmichConfig
    cache: CacheConfig
    display: DisplayConfig = field(default_factory=DisplayConfig)
    sync: SyncConfig = field(default_factory=SyncConfig)
    web: WebConfig = field(default_factory=WebConfig)

    @staticmethod
    def from_dict(raw: dict[str, Any], base_dir: Path) -> "AppConfig":
        immich_raw = raw.get("immich", {})
        cache = raw.get("cache", {})
        display = raw.get("display", {})
        sync = raw.get("sync", {})
        web = raw.get("web", {})

        immich = ImmichConfig(
            base_url=str(immich_raw.get("base_url", "http://localhost:2283")).rstrip("/"),
            api_key=str(immich_raw.get("api_key", "")),
            albums=list(immich_raw.get("albums", [])),
            request_timeout_seconds=float(immich_raw.get("request_timeout_seconds", 30.0)),
        )
        cache_config = CacheConfig(
            directory=_resolve_path(base_dir, cache["directory"]),
            metadata_file=_resolve_path(base_dir, cache["metadata_file"]),
            max_disk_usage_percent=int(cache.get("max_disk_usage_percent", 80)),
            min_free_space_mb=int(cache.get("min_free_space_mb", 512)),
        )
        display_config = DisplayConfig(
            slide_seconds=int(display.get("slide_seconds", DEFAULT_SLIDE_SECONDS)),
            transition_seconds=float(display.get("transition_seconds", DEFAULT_TRANSITION_SECONDS)),
            mode=str(display.get("mode", DEFAULT_MODE)),
        )
        sync_config = SyncConfig(interval_minutes=int(sync.get("interval_minutes", 30)))
        web_config = WebConfig(
            host=str(web.get("host", "0.0.0.0")),
            port=int(web.get("port", 8080)),
            auth_token=str(web.get("auth_token", "")).strip(),
        )

        return AppConfig(
            immich=immich,
            cache=cache_config,
            display=display_config,
            sync=sync_config,
            web=web_config,
        )

    def to_dict(self, base_dir: Path) -> dict[str, Any]:
        return {
            "immich": {
                "base_url": self.immich.base_url,
                "api_key": self.immich.api_key,
                "albums": list(self.immich.albums),
                "request_timeout_seconds": self.immich.request_timeout_seconds,
            },
            "cache": {
                "directory": _path_to_config_value(self.cache.directory, base_dir),
                "metadata_file": _path_to_config_value(self.cache.metadata_file, base_dir),
                "max_disk_usage_percent": self.cache.max_disk_usage_percent,
                "min_free_space_mb": self.cache.min_free_space_mb,
            },
            "display": {
                "slide_seconds": self.display.slide_seconds,
                "transition_seconds": self.display.transition_seconds,
                "mode": self.display.mode,
            },
            "sync": {
                "interval_minutes": self.sync.interval_minutes,
            },
            "web": {
                "host": self.web.host,
                "port": self.web.port,
                "auth_token": self.web.auth_token,
            },
        }


def load_config(path: str | Path) -> AppConfig:
    """Parse a TOML file into an :class:`AppConfig`."""
    config_path = Path(path).expanduser().resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    return AppConfig.from_dict(raw, base_dir=config_path.parent)


def save_config(path: str | Path, config: AppConfig) -> None:
    """Serialize an :class:`AppConfig` back to TOML on disk."""
    config_path = Path(path).expanduser().resolve()
    payload = config.to_dict(base_dir=config_path.parent)
    config_path.write_text(tomli_w.dumps(payload), encoding="utf-8")


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (base_dir / path).resolve()


def _path_to_config_value(path: Path, base_dir: Path) -> str:
    path = path.expanduser().resolve()
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)
