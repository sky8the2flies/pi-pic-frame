"""Immich photo provider using the public REST API."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from picture_frame.providers.base import PhotoAsset

logger = logging.getLogger(__name__)

_IMAGE_ASSET_TYPES = frozenset({"IMAGE", "image"})
_DEFAULT_PAGE_SIZE = 250
_MAX_ERROR_DETAIL_CHARS = 200


class ImmichError(RuntimeError):
    """Raised for any Immich API failure (network, auth, protocol)."""


@dataclass(slots=True)
class ImmichSettings:
    base_url: str
    api_key: str
    request_timeout_seconds: float = 30.0


class ImmichProvider:
    """Minimal Immich client scoped to the picture frame's needs."""

    def __init__(self, settings: ImmichSettings) -> None:
        self._settings = settings

    def authenticate(self) -> None:
        """Verify credentials by pinging the server; raises ImmichError on failure."""
        if not self._settings.base_url:
            raise ImmichError("Immich base_url is not configured")
        if not self._settings.api_key:
            raise ImmichError("Immich api_key is not configured")
        try:
            self._request("GET", "/api/server/ping")
        except ImmichError:
            # Older Immich versions expose the ping under /api/server-info.
            self._request("GET", "/api/server-info/ping")

    def list_albums(self) -> list[dict[str, object]]:
        """Return album summaries sorted alphabetically by title."""
        payload = self._request("GET", "/api/albums")
        albums: list[dict[str, object]] = []
        for album in payload or []:
            albums.append(
                {
                    "id": str(album.get("id", "")),
                    "title": str(album.get("albumName") or album.get("name") or "(untitled)"),
                    "asset_count": int(album.get("assetCount", 0) or 0),
                    "is_shared": bool(album.get("shared", False)),
                }
            )
        albums.sort(key=lambda item: str(item.get("title", "")).lower())
        return [album for album in albums if album["id"]]

    def list_assets(self, album_id: str) -> list[PhotoAsset]:
        """Enumerate image assets in an album via ``/api/search/metadata``."""
        results: list[PhotoAsset] = []
        page = 1
        while True:
            payload = self._request(
                "POST",
                "/api/search/metadata",
                body={
                    "albumIds": [album_id],
                    "type": "IMAGE",
                    "withExif": True,
                    "page": page,
                    "size": _DEFAULT_PAGE_SIZE,
                },
            ) or {}
            container = payload.get("assets") or {}
            items = container.get("items") if isinstance(container, dict) else None
            if not items:
                # Some Immich versions still return the raw list under "assets".
                items = payload.get("assets") if isinstance(payload.get("assets"), list) else []
            for asset in items or []:
                normalized = self._normalize_asset(asset)
                if normalized is not None:
                    results.append(normalized)
            next_page = container.get("nextPage") if isinstance(container, dict) else None
            if not next_page:
                break
            try:
                page = int(next_page)
            except (TypeError, ValueError):
                break
        logger.debug("Immich album %s → %d image assets", album_id, len(results))
        return results

    def download_asset(self, asset: PhotoAsset, destination: Path) -> int:
        """Fetch the original bytes for ``asset`` and write them to ``destination``."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = Request(asset.source_url, headers=self._auth_headers())
        try:
            with urlopen(request, timeout=self._settings.request_timeout_seconds) as response:
                content = response.read()
        except HTTPError as exc:
            raise ImmichError(
                f"Immich download failed for asset {asset.media_id}: HTTP {exc.code}"
            ) from exc
        except URLError as exc:
            raise ImmichError(
                f"Immich download failed for asset {asset.media_id}: {exc.reason}"
            ) from exc
        destination.write_bytes(content)
        return len(content)

    def _normalize_asset(self, asset: dict[str, object]) -> PhotoAsset | None:
        asset_type = str(asset.get("type", ""))
        if asset_type not in _IMAGE_ASSET_TYPES:
            return None
        media_id = str(asset.get("id", ""))
        if not media_id:
            return None
        filename = str(
            asset.get("originalFileName")
            or str(asset.get("originalPath", "")).split("/")[-1]
            or f"{media_id}.jpg"
        )
        exif = asset.get("exifInfo") if isinstance(asset.get("exifInfo"), dict) else None
        size_hint = exif.get("fileSizeInByte") if isinstance(exif, dict) else None
        return PhotoAsset(
            media_id=media_id,
            filename=filename,
            mime_type=str(asset.get("originalMimeType") or "image/jpeg"),
            source_url=self._build_url(f"/api/assets/{media_id}/original"),
            created_time=asset.get("fileCreatedAt") or asset.get("createdAt"),
            size_hint_bytes=int(size_hint) if size_hint else None,
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._settings.api_key,
            "Accept": "application/json",
        }

    def _build_url(self, path: str) -> str:
        base = self._settings.base_url.rstrip("/") + "/"
        return urljoin(base, path.lstrip("/"))

    def _request(self, method: str, path: str, body: Any | None = None) -> Any:
        url = self._build_url(path)
        headers = self._auth_headers()
        data: bytes | None = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=self._settings.request_timeout_seconds) as response:
                raw = response.read()
        except HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", errors="ignore")
            except OSError:
                logger.debug("Failed to read HTTPError body", exc_info=True)
            raise ImmichError(
                f"Immich {method} {path} failed: HTTP {exc.code} "
                f"{detail[:_MAX_ERROR_DETAIL_CHARS]}"
            ) from exc
        except URLError as exc:
            raise ImmichError(f"Immich {method} {path} failed: {exc.reason}") from exc
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ImmichError(f"Immich {method} {path} returned invalid JSON") from exc
