from picture_frame.config import (
    AppConfig,
    CacheConfig,
    DisplayConfig,
    ImmichConfig,
    SyncConfig,
    WebConfig,
)
from picture_frame.runtime import PictureFrameRuntime
from picture_frame.web import create_app


def _mk_runtime(tmp_path, *, auth_token: str = ""):
    config = AppConfig(
        immich=ImmichConfig(
            base_url="http://localhost:2283",
            api_key="",
            albums=["album-1"],
        ),
        cache=CacheConfig(
            directory=tmp_path / "cache",
            metadata_file=tmp_path / "cache" / "metadata.json",
            max_disk_usage_percent=80,
            min_free_space_mb=0,
        ),
        display=DisplayConfig(),
        sync=SyncConfig(interval_minutes=30),
        web=WebConfig(host="127.0.0.1", port=8080, auth_token=auth_token),
    )
    runtime = PictureFrameRuntime(config)
    runtime.state.set_images([tmp_path / "cache" / "img.jpg"])
    return runtime


def test_index_renders_template(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    for path in ("/", "/setup"):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Picture Frame Console" in html
        assert "app.js" in html


def test_static_assets_served(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    css = client.get("/static/style.css")
    js = client.get("/static/app.js")
    assert css.status_code == 200
    assert js.status_code == 200
    assert b"--primary" in css.get_data()
    assert b"TOKEN_STORAGE_KEY" in js.get_data()


def test_status_reports_full_config(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    data = client.get("/status").get_json()
    assert data["albums"] == ["album-1"]
    assert data["immich_base_url"] == "http://localhost:2283"
    assert data["immich_configured"] is False
    assert data["display"]["mode"] == "fit_blur"
    assert data["display"]["slide_seconds"] == 20
    assert data["display"]["transition_seconds"] == 0.8
    assert data["sync_interval_minutes"] == 30
    assert data["last_error"] is None


def test_playback_controls_update_state(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    assert client.post("/control/pause").status_code == 200
    assert runtime.state.paused is True
    assert client.post("/control/resume").status_code == 200
    assert runtime.state.paused is False
    assert client.post("/control/next").status_code == 202
    assert runtime.state.consume_delta() == 1
    assert client.post("/control/previous").status_code == 202
    assert runtime.state.consume_delta() == -1


def test_set_immich_credentials_persists_and_validates(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    captured = {}

    def _fake_set(base_url, api_key):
        captured["base_url"] = base_url
        captured["api_key"] = api_key
        runtime.config.immich.base_url = base_url
        runtime.config.immich.api_key = api_key

    runtime.set_immich_credentials = _fake_set  # type: ignore[method-assign]

    response = client.post(
        "/config/immich",
        json={"base_url": "http://localhost:2283", "api_key": "abc123"},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert captured == {"base_url": "http://localhost:2283", "api_key": "abc123"}


def test_list_immich_albums_endpoint(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    runtime.list_available_albums = lambda: [  # type: ignore[method-assign]
        {"id": "a1", "title": "One", "asset_count": 5, "is_shared": False},
    ]

    data = client.get("/immich/albums").get_json()
    assert data["ok"] is True
    assert data["result"]["albums"][0]["id"] == "a1"


def test_set_albums_endpoint(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    captured = {}

    def _fake_update(albums, sync_now=False):
        captured["albums"] = albums
        captured["sync_now"] = sync_now
        runtime.config.immich.albums = albums
        return {"albums": albums}

    runtime.update_albums = _fake_update  # type: ignore[method-assign]

    response = client.post(
        "/config/albums",
        json={"albums": ["a1", "a2"], "sync_now": True},
    )
    assert response.status_code == 200
    assert captured == {"albums": ["a1", "a2"], "sync_now": True}
    assert runtime.config.immich.albums == ["a1", "a2"]


def test_set_display_settings(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    response = client.post(
        "/config/display",
        json={"slide_seconds": 5, "transition_seconds": 1.5, "mode": "fit"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["result"] == {
        "slide_seconds": 5,
        "transition_seconds": 1.5,
        "mode": "fit",
    }


def test_set_sync_interval(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    response = client.post("/config/sync", json={"interval_minutes": 10})
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["result"] == {"interval_minutes": 10}
    assert runtime.config.sync.interval_minutes == 10


def test_set_sync_interval_rejects_invalid(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    assert client.post("/config/sync", json={}).status_code == 400
    assert client.post("/config/sync", json={"interval_minutes": 0}).status_code == 400
    assert client.post("/config/sync", json={"interval_minutes": 2000}).status_code == 400
    assert client.post("/config/sync", json={"interval_minutes": "soon"}).status_code == 400


def test_status_includes_cache_stats(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    data = client.get("/status").get_json()
    cache = data["cache"]
    assert cache["max_disk_usage_percent"] == 80
    assert cache["min_free_space_mb"] == 0
    assert cache["cached_files"] == 0
    assert cache["cached_bytes"] == 0
    assert "disk" in cache
    assert "total_bytes" in cache["disk"]


def test_set_cache_settings(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    response = client.post(
        "/config/cache",
        json={"max_disk_usage_percent": 60, "min_free_space_mb": 1024},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["ok"] is True
    assert body["result"] == {"max_disk_usage_percent": 60, "min_free_space_mb": 1024}
    assert runtime.config.cache.max_disk_usage_percent == 60
    assert runtime.config.cache.min_free_space_mb == 1024


def test_set_cache_settings_rejects_out_of_range(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    assert client.post("/config/cache", json={"max_disk_usage_percent": 5}).status_code == 400
    assert client.post("/config/cache", json={"max_disk_usage_percent": 120}).status_code == 400
    assert client.post("/config/cache", json={"min_free_space_mb": -1}).status_code == 400
    assert client.post("/config/cache", json={"max_disk_usage_percent": "nope"}).status_code == 400


def test_set_display_settings_rejects_invalid_mode(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    response = client.post("/config/display", json={"mode": "sparkle"})
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_auth_required_blocks_unauthed_calls(tmp_path):
    runtime = _mk_runtime(tmp_path, auth_token="s3cret")
    app = create_app(runtime)
    client = app.test_client()

    # Public endpoints stay open.
    assert client.get("/health").status_code == 200
    assert client.get("/auth/config").get_json() == {"auth_required": True}
    assert client.get("/").status_code == 200
    assert client.get("/static/style.css").status_code == 200

    # Protected endpoints reject unauthenticated calls.
    assert client.get("/status").status_code == 401
    assert client.post("/control/pause").status_code == 401


def test_auth_required_accepts_bearer_token(tmp_path):
    runtime = _mk_runtime(tmp_path, auth_token="s3cret")
    app = create_app(runtime)
    client = app.test_client()

    headers = {"Authorization": "Bearer s3cret"}
    assert client.get("/status", headers=headers).status_code == 200
    assert client.post("/control/pause", headers=headers).status_code == 200
    assert runtime.state.paused is True

    # Wrong scheme or token is rejected.
    assert client.get("/status", headers={"Authorization": "Basic s3cret"}).status_code == 401
    assert client.get("/status", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_stop_requires_confirmation_header(tmp_path):
    runtime = _mk_runtime(tmp_path)
    app = create_app(runtime)
    client = app.test_client()

    assert client.post("/stop").status_code == 403
    assert runtime.state.stop is False

    response = client.post("/stop", headers={"X-Allow-Stop": "true"})
    assert response.status_code == 200
    assert runtime.state.stop is True
