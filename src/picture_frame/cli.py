"""Console script entry points."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
from pathlib import Path

from picture_frame.config import load_config
from picture_frame.display import SlideshowRenderer
from picture_frame.logging_setup import configure_logging
from picture_frame.runtime import PictureFrameRuntime
from picture_frame.web import create_app

logger = logging.getLogger(__name__)


def _common_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.toml", help="Path to TOML config")
    parser.add_argument("--log-level", default="INFO", help="Python logging level")
    parser.add_argument("--host", default=None, help="Override web.host from config")
    parser.add_argument("--port", type=int, default=None, help="Override web.port from config")
    parser.add_argument(
        "--immich-base-url",
        default=None,
        help=(
            "Override [immich].base_url without writing to config. "
            "Useful when the same config is shared between host and container."
        ),
    )
    parser.add_argument(
        "--immich-api-key",
        default=None,
        help="Override [immich].api_key without writing to config.",
    )
    return parser


def _runtime_from_args() -> tuple[PictureFrameRuntime, argparse.Namespace]:
    parser = _common_parser()
    args = parser.parse_args()
    configure_logging(args.log_level)
    config_path = Path(args.config).expanduser().resolve()
    if not config_path.exists():
        logger.error("Config file not found: %s", config_path)
        sys.exit(2)
    config = load_config(config_path)
    if args.host is not None:
        config.web.host = args.host
    if args.port is not None:
        config.web.port = args.port

    # Immich overrides: CLI flag > env var > config file. These are in-memory
    # only so shared configs (host + docker) can coexist.
    base_url_override = args.immich_base_url or os.environ.get("PICTURE_FRAME_IMMICH_BASE_URL")
    if base_url_override:
        config.immich.base_url = base_url_override.rstrip("/")
        logger.info("Immich base URL overridden to %s", config.immich.base_url)
    api_key_override = args.immich_api_key or os.environ.get("PICTURE_FRAME_IMMICH_API_KEY")
    if api_key_override:
        config.immich.api_key = api_key_override

    runtime = PictureFrameRuntime(config, config_path=config_path)
    _install_signal_handlers(runtime)
    return runtime, args


def _install_signal_handlers(runtime: PictureFrameRuntime) -> None:
    def _handler(signum, _frame):
        logger.info("Received signal %s; shutting down", signal.Signals(signum).name)
        runtime.request_stop()
        # Convert the signal to KeyboardInterrupt so blocking servers
        # (waitress) and the pygame loop unwind cleanly.
        raise KeyboardInterrupt

    # SIGINT is already delivered as KeyboardInterrupt by Python; only override
    # SIGTERM so systemd/docker stop signals get the same treatment.
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError):
        pass


def _serve_wsgi(runtime: PictureFrameRuntime) -> None:
    from waitress import serve  # imported lazily to keep startup lean

    logger.info("Serving on http://%s:%d", runtime.config.web.host, runtime.config.web.port)
    app = create_app(runtime)
    try:
        serve(
            app,
            host=runtime.config.web.host,
            port=runtime.config.web.port,
            threads=8,
        )
    except KeyboardInterrupt:
        logger.info("Web server stopped")


def run_sync() -> None:
    runtime, _ = _runtime_from_args()
    try:
        stats = runtime.sync_now()
    except Exception as exc:
        logger.error("Sync failed: %s", exc)
        sys.exit(1)
    print(stats)


def run_display() -> None:
    runtime, _ = _runtime_from_args()
    runtime.refresh_images()
    runtime.start_sync_loop()
    SlideshowRenderer(runtime, runtime.config.display).run()


def run_web() -> None:
    runtime, _ = _runtime_from_args()
    runtime.refresh_images()
    runtime.start_sync_loop()
    _serve_wsgi(runtime)


def run_headless() -> None:
    runtime, _ = _runtime_from_args()
    runtime.refresh_images()
    runtime.start_sync_loop()
    _serve_wsgi(runtime)


def run_app() -> None:
    runtime, _ = _runtime_from_args()
    runtime.refresh_images()
    runtime.start_sync_loop()

    web_thread = threading.Thread(
        target=_serve_wsgi,
        args=(runtime,),
        name="picture-frame-web",
        daemon=True,
    )
    web_thread.start()

    SlideshowRenderer(runtime, runtime.config.display).run()
