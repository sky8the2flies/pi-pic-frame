"""Centralized logging configuration."""

from __future__ import annotations

import logging
import os

_DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


def configure_logging(level: str | int = "INFO") -> None:
    """Configure the root logger idempotently.

    Honours the ``PICTURE_FRAME_LOG_LEVEL`` env var when set; otherwise uses
    the supplied ``level`` (accepts either a level name or integer constant).
    """
    env_level = os.environ.get("PICTURE_FRAME_LOG_LEVEL")
    if env_level:
        level = env_level
    if isinstance(level, str):
        resolved = getattr(logging, level.upper(), logging.INFO)
    else:
        resolved = level

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=resolved, format=_DEFAULT_FORMAT)
    else:
        root.setLevel(resolved)
    # Quiet very chatty third-party loggers by default.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
