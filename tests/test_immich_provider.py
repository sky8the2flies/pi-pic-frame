import io
import json
from urllib.error import HTTPError

import pytest

from picture_frame.providers.immich import ImmichError, ImmichProvider, ImmichSettings


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _mk_provider():
    return ImmichProvider(
        ImmichSettings(base_url="http://immich.local:2283/", api_key="key-1")
    )


def test_provider_lists_albums(monkeypatch):
    provider = _mk_provider()
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        return _FakeResponse(
            [
                {"id": "a1", "albumName": "Vacation", "assetCount": 12, "shared": False},
                {"id": "a2", "name": "Wedding", "assetCount": 3, "shared": True},
            ]
        )

    monkeypatch.setattr("picture_frame.providers.immich.urlopen", fake_urlopen)

    albums = provider.list_albums()

    assert captured["url"] == "http://immich.local:2283/api/albums"
    assert captured["headers"]["X-api-key"] == "key-1"
    assert [a["title"] for a in albums] == ["Vacation", "Wedding"]
    assert albums[0]["asset_count"] == 12
    assert albums[1]["is_shared"] is True


def test_provider_lists_assets_in_album(monkeypatch):
    provider = _mk_provider()
    captured_bodies = []

    def fake_urlopen(request, timeout=None):
        assert request.full_url == "http://immich.local:2283/api/search/metadata"
        captured_bodies.append(json.loads(request.data.decode("utf-8")))
        return _FakeResponse(
            {
                "assets": {
                    "items": [
                        {
                            "id": "asset-1",
                            "type": "IMAGE",
                            "originalFileName": "one.jpg",
                            "originalMimeType": "image/jpeg",
                            "exifInfo": {"fileSizeInByte": 12345},
                            "fileCreatedAt": "2024-01-01T00:00:00Z",
                        },
                        {
                            "id": "asset-2",
                            "type": "VIDEO",
                            "originalFileName": "clip.mp4",
                        },
                    ],
                    "nextPage": None,
                }
            }
        )

    monkeypatch.setattr("picture_frame.providers.immich.urlopen", fake_urlopen)

    assets = provider.list_assets("album-1")

    assert captured_bodies[0]["albumIds"] == ["album-1"]
    assert captured_bodies[0]["type"] == "IMAGE"
    assert [a.media_id for a in assets] == ["asset-1"]
    assert assets[0].filename == "one.jpg"
    assert assets[0].source_url == "http://immich.local:2283/api/assets/asset-1/original"
    assert assets[0].size_hint_bytes == 12345


def test_provider_download_asset_writes_file(monkeypatch, tmp_path):
    provider = _mk_provider()

    class _BytesResponse:
        def __init__(self, data):
            self._data = data

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout=None):
        assert request.headers.get("X-api-key") == "key-1"
        return _BytesResponse(b"binary-data")

    monkeypatch.setattr("picture_frame.providers.immich.urlopen", fake_urlopen)

    from picture_frame.providers.base import PhotoAsset

    asset = PhotoAsset(
        media_id="a1",
        filename="a.jpg",
        mime_type="image/jpeg",
        source_url="http://immich.local:2283/api/assets/a1/original",
    )
    destination = tmp_path / "a1.jpg"

    written = provider.download_asset(asset, destination)

    assert written == len(b"binary-data")
    assert destination.read_bytes() == b"binary-data"


def test_provider_authenticate_requires_url_and_key():
    with pytest.raises(ImmichError):
        ImmichProvider(ImmichSettings(base_url="", api_key="k")).authenticate()
    with pytest.raises(ImmichError):
        ImmichProvider(ImmichSettings(base_url="http://x", api_key="")).authenticate()


def test_provider_wraps_http_error(monkeypatch):
    provider = _mk_provider()

    def fake_urlopen(request, timeout=None):
        raise HTTPError(request.full_url, 401, "Unauthorized", {}, io.BytesIO(b"nope"))

    monkeypatch.setattr("picture_frame.providers.immich.urlopen", fake_urlopen)

    with pytest.raises(ImmichError):
        provider.list_albums()
