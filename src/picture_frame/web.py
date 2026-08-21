"""Flask app exposing status, configuration, and playback control."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

from flask import Flask, abort, jsonify, render_template, request

from picture_frame.runtime import PictureFrameRuntime

logger = logging.getLogger(__name__)

_STOP_CONFIRM_HEADER = "X-Allow-Stop"


def create_app(runtime: PictureFrameRuntime) -> Flask:
    """Build the Flask application bound to a runtime instance."""
    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
    )
    app.url_map.strict_slashes = False

    def _requires_auth() -> bool:
        return bool(runtime.config.web.auth_token)

    def _token_ok(header_value: str | None) -> bool:
        if not _requires_auth():
            return True
        expected = runtime.config.web.auth_token
        if not header_value:
            return False
        scheme, _, token = header_value.partition(" ")
        if scheme.lower() != "bearer":
            return False
        return secrets.compare_digest(token.strip(), expected)

    def _require_auth(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if not _token_ok(request.headers.get("Authorization")):
                return jsonify({"ok": False, "error": "authentication required"}), 401
            return view(*args, **kwargs)

        return wrapper

    @app.get("/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.get("/auth/config")
    def auth_config() -> tuple[dict[str, bool], int]:
        return {"auth_required": _requires_auth()}, 200

    @app.get("/")
    @app.get("/setup")
    def index() -> str:
        return render_template("index.html")

    @app.get("/status")
    @_require_auth
    def status() -> tuple[dict[str, object], int]:
        state = runtime.state
        last_sync = None
        if state.last_sync_ts:
            last_sync = datetime.fromtimestamp(
                state.last_sync_ts, tz=timezone.utc
            ).isoformat()
        display = runtime.config.display
        return (
            {
                "paused": state.paused,
                "image_count": len(state.images),
                "current_index": state.current_index,
                "last_sync": last_sync,
                "last_sync_stats": state.last_sync_stats,
                "last_error": state.last_error,
                "albums": runtime.config.immich.albums,
                "immich_base_url": runtime.config.immich.base_url,
                "immich_configured": runtime.immich_configured(),
                "display": {
                    "slide_seconds": display.slide_seconds,
                    "transition_seconds": display.transition_seconds,
                    "mode": display.mode,
                },
                "sync_interval_minutes": runtime.config.sync.interval_minutes,
                "cache": runtime.cache_stats(),
                "rotation": runtime.rotation_stats(),
            },
            200,
        )

    @app.post("/config/immich")
    @_require_auth
    def set_immich() -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        base_url = str(payload.get("base_url", "")).strip()
        api_key = str(payload.get("api_key", "")).strip()
        try:
            runtime.set_immich_credentials(base_url=base_url, api_key=api_key)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        except Exception as exc:
            logger.exception("Setting Immich credentials failed")
            return {"ok": False, "error": str(exc)}, 502
        return {"ok": True, "result": {"base_url": runtime.config.immich.base_url}}, 200

    @app.get("/immich/albums")
    @_require_auth
    def list_immich_albums() -> tuple[dict[str, object], int]:
        try:
            albums = runtime.list_available_albums()
        except Exception as exc:
            logger.exception("Listing Immich albums failed")
            return {"ok": False, "error": str(exc)}, 502
        return {"ok": True, "result": {"albums": albums}}, 200

    @app.post("/config/albums")
    @_require_auth
    def set_albums() -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        albums = payload.get("albums")
        sync_now = bool(payload.get("sync_now", False))
        if not isinstance(albums, list):
            return {"ok": False, "error": "albums must be a list of album ids"}, 400
        try:
            updated = runtime.update_albums(albums=albums, sync_now=sync_now)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        except Exception as exc:
            logger.exception("Saving albums failed")
            return {"ok": False, "error": str(exc)}, 502
        return {"ok": True, "result": updated}, 200

    @app.post("/config/display")
    @_require_auth
    def set_display() -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        kwargs: dict[str, object] = {}
        if "slide_seconds" in payload:
            try:
                kwargs["slide_seconds"] = int(payload["slide_seconds"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "slide_seconds must be an integer"}, 400
        if "transition_seconds" in payload:
            try:
                kwargs["transition_seconds"] = float(payload["transition_seconds"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "transition_seconds must be a number"}, 400
        if "mode" in payload:
            kwargs["mode"] = str(payload["mode"])
        try:
            updated = runtime.update_display_settings(**kwargs)  # type: ignore[arg-type]
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {"ok": True, "result": updated}, 200

    @app.post("/config/sync")
    @_require_auth
    def set_sync() -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        if "interval_minutes" not in payload:
            return {"ok": False, "error": "interval_minutes is required"}, 400
        try:
            interval_minutes = int(payload["interval_minutes"])
        except (TypeError, ValueError):
            return {"ok": False, "error": "interval_minutes must be an integer"}, 400
        try:
            updated = runtime.update_sync_settings(interval_minutes=interval_minutes)
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {"ok": True, "result": updated}, 200

    @app.post("/config/cache")
    @_require_auth
    def set_cache() -> tuple[dict[str, object], int]:
        payload = request.get_json(silent=True) or {}
        kwargs: dict[str, object] = {}
        if "max_disk_usage_percent" in payload:
            try:
                kwargs["max_disk_usage_percent"] = int(payload["max_disk_usage_percent"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "max_disk_usage_percent must be an integer"}, 400
        if "min_free_space_mb" in payload:
            try:
                kwargs["min_free_space_mb"] = int(payload["min_free_space_mb"])
            except (TypeError, ValueError):
                return {"ok": False, "error": "min_free_space_mb must be an integer"}, 400
        try:
            updated = runtime.update_cache_settings(**kwargs)  # type: ignore[arg-type]
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
        return {"ok": True, "result": updated}, 200

    @app.post("/control/pause")
    @_require_auth
    def pause() -> tuple[dict[str, bool], int]:
        runtime.state.paused = True
        return {"paused": True}, 200

    @app.post("/control/resume")
    @_require_auth
    def resume() -> tuple[dict[str, bool], int]:
        runtime.state.paused = False
        return {"paused": False}, 200

    @app.post("/control/next")
    @_require_auth
    def next_image() -> tuple[dict[str, bool], int]:
        runtime.state.request_next()
        return {"queued": True}, 202

    @app.post("/control/previous")
    @_require_auth
    def previous_image() -> tuple[dict[str, bool], int]:
        runtime.state.request_previous()
        return {"queued": True}, 202

    @app.post("/sync")
    @_require_auth
    def sync_now() -> tuple[dict[str, object], int]:
        try:
            result = runtime.sync_now()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}, 500
        return {"ok": True, "result": result}, 200

    @app.post("/stop")
    @_require_auth
    def stop() -> tuple[dict[str, bool], int]:
        if request.headers.get(_STOP_CONFIRM_HEADER, "") != "true":
            return {"ok": False, "error": f"missing {_STOP_CONFIRM_HEADER} header"}, 403
        runtime.request_stop()
        return {"ok": True}, 200

    @app.errorhandler(404)
    def _not_found(_err):
        if request.path.startswith("/api") or request.headers.get("Accept", "").startswith(
            "application/json"
        ):
            return jsonify({"ok": False, "error": "not found"}), 404
        abort(404)

    return app
