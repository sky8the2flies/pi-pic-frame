from pathlib import Path

from picture_frame.cache import PhotoCache
from picture_frame.config import CacheConfig
from picture_frame.providers.base import PhotoAsset


class _StubProvider:
    def authenticate(self):
        return None

    def list_assets(self, album_id):
        return []

    def download_asset(self, asset, destination: Path):
        destination.write_bytes(f"asset:{asset.media_id}".encode("utf-8"))
        return destination.stat().st_size


def _mk_cache(tmp_path):
    cfg = CacheConfig(
        directory=tmp_path / "cache",
        metadata_file=tmp_path / "cache" / "metadata.json",
        max_disk_usage_percent=80,
        min_free_space_mb=0,
    )
    return PhotoCache(cfg)


def test_cache_sync_is_idempotent(tmp_path):
    cache = _mk_cache(tmp_path)
    provider = _StubProvider()
    asset = PhotoAsset(
        media_id="abc",
        filename="photo.jpg",
        mime_type="image/jpeg",
        source_url="unused",
    )

    first = cache.sync_assets("stub", [asset], provider)
    second = cache.sync_assets("stub", [asset], provider)

    assert first["downloaded"] == 1
    assert second["downloaded"] == 0
    assert second["skipped"] == 1


def test_cache_evicts_oldest_when_over_quota(tmp_path, monkeypatch):
    cache = _mk_cache(tmp_path)
    provider = _StubProvider()
    asset1 = PhotoAsset(
        media_id="old",
        filename="old.jpg",
        mime_type="image/jpeg",
        source_url="unused",
        size_hint_bytes=1,
    )
    asset2 = PhotoAsset(
        media_id="new",
        filename="new.jpg",
        mime_type="image/jpeg",
        source_url="unused",
        size_hint_bytes=1,
    )

    class _Du:
        total = 100
        used = 79
        free = 21

    monkeypatch.setattr("picture_frame.cache.disk_usage", lambda _: _Du())
    cache.sync_assets("stub", [asset1], provider)
    assert "old" in {entry.media_id for entry in cache.entries()}

    class _OverDu:
        total = 100
        used = 80
        free = 20

    monkeypatch.setattr("picture_frame.cache.disk_usage", lambda _: _OverDu())
    cache.sync_assets("stub", [asset2], provider)

    ids = {entry.media_id for entry in cache.entries()}
    assert "new" in ids
    assert "old" not in ids
