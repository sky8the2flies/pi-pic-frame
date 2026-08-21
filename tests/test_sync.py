import json
from types import SimpleNamespace

from picture_frame.cache import PhotoCache
from picture_frame.config import CacheConfig
from picture_frame.providers.base import PhotoAsset
from picture_frame.sync import SyncEngine, select_rotation_window


def _cache_config(tmp_path):
    return CacheConfig(
        directory=tmp_path / "cache",
        metadata_file=tmp_path / "cache" / "metadata.json",
        max_disk_usage_percent=80,
        min_free_space_mb=0,
    )


def test_select_rotation_window_wraps_and_preserves_order():
    ids = [f"id-{i}" for i in range(10)]

    selected = select_rotation_window(ids, start=8, window_size=5)

    assert selected == ["id-8", "id-9", "id-0", "id-1", "id-2"]


def test_two_sync_windows_cover_all_assets_with_smaller_capacity():
    ids = [f"id-{i}" for i in range(50)]

    first = select_rotation_window(ids, start=0, window_size=45)
    second = select_rotation_window(ids, start=45, window_size=45)

    assert len(first) == 45
    assert len(second) == 45
    assert set(first) | set(second) == set(ids)


def test_rotation_state_persists_in_cache_metadata(tmp_path):
    config = _cache_config(tmp_path)
    cache = PhotoCache(config)

    cache.set_rotation_state(total_assets=50, next_index=45)

    reloaded = PhotoCache(config)
    assert reloaded.get_rotation_state() == {"total_assets": 50, "next_index": 45}


def test_rotation_state_defaults_for_legacy_cache_metadata(tmp_path):
    config = _cache_config(tmp_path)
    config.directory.mkdir(parents=True)
    config.metadata_file.write_text(json.dumps({"entries": []}), encoding="utf-8")

    cache = PhotoCache(config)

    assert cache.get_rotation_state() == {"total_assets": 0, "next_index": 0}


def test_sync_once_rotates_deterministically_and_advances_cursor():
    assets = [
        PhotoAsset(media_id=media_id, filename=f"{media_id}.jpg", mime_type="image/jpeg", source_url="")
        for media_id in ("c", "a", "b")
    ]

    class _Provider:
        def authenticate(self):
            return None

        def list_assets(self, _album_id):
            return assets

    class _Cache:
        def __init__(self):
            self.rotation = {"total_assets": 0, "next_index": 0}
            self.synced = []

        def entries(self):
            return [object(), object()]

        def get_rotation_state(self):
            return dict(self.rotation)

        def set_rotation_state(self, total_assets, next_index):
            self.rotation = {"total_assets": total_assets, "next_index": next_index}

        def sync_assets(self, provider_name, assets, provider):
            self.synced.append([asset.media_id for asset in assets])
            return {"downloaded": 0, "skipped": 0, "evicted": 0, "failed": 0}

    engine = SyncEngine.__new__(SyncEngine)
    engine._config = SimpleNamespace(immich=SimpleNamespace(albums=["album"]))
    engine._provider = _Provider()
    engine._cache = _Cache()

    engine.sync_once()
    engine.sync_once()

    assert engine._cache.synced == [["a", "b"], ["c", "a"]]
    assert engine._cache.rotation == {"total_assets": 3, "next_index": 1}


def test_rotated_sync_downloads_only_newly_entering_assets_near_quota(tmp_path, monkeypatch):
    assets = [
        PhotoAsset(
            media_id=f"id-{index:02d}",
            filename=f"id-{index:02d}.jpg",
            mime_type="image/jpeg",
            source_url="",
            size_hint_bytes=1,
        )
        for index in range(50)
    ]

    class _Provider:
        def __init__(self):
            self.downloaded_ids = []

        def authenticate(self):
            return None

        def list_assets(self, _album_id):
            return assets

        def download_asset(self, asset, destination):
            self.downloaded_ids.append(asset.media_id)
            destination.write_bytes(b"x")
            return 1

    provider = _Provider()
    cache = PhotoCache(_cache_config(tmp_path))
    monkeypatch.setattr(cache, "_violates_limits", lambda _incoming: len(cache.entries()) >= 45)

    cache.sync_assets("immich", assets[:45], provider)
    cache.set_rotation_state(total_assets=50, next_index=45)
    provider.downloaded_ids.clear()

    engine = SyncEngine.__new__(SyncEngine)
    engine._config = SimpleNamespace(immich=SimpleNamespace(albums=["album"]))
    engine._provider = provider
    engine._cache = cache

    result = engine.sync_once()

    assert result["downloaded"] == 5
    assert provider.downloaded_ids == [f"id-{index:02d}" for index in range(45, 50)]
