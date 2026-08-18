from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(slots=True)
class PhotoAsset:
    media_id: str
    filename: str
    mime_type: str
    source_url: str
    created_time: str | None = None
    size_hint_bytes: int | None = None


class PhotoProvider(Protocol):
    def authenticate(self) -> None:
        """Ensure credentials are present and usable."""

    def list_assets(self, album_id: str) -> list[PhotoAsset]:
        """Return available assets for a source identifier (album)."""

    def download_asset(self, asset: PhotoAsset, destination: Path) -> int:
        """Download asset to destination path and return written bytes."""
