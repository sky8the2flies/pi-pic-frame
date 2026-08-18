"""Fullscreen slideshow renderer built on pygame."""

from __future__ import annotations

import logging
import time
from pathlib import Path

import pygame
from PIL import Image, ImageFilter

from picture_frame.config import DisplayConfig
from picture_frame.runtime import PictureFrameRuntime

logger = logging.getLogger(__name__)

_CACHE_RESCAN_INTERVAL_S = 5.0
_IDLE_FRAMES_PER_SECOND = 30
_TRANSITION_FRAMES_PER_SECOND = 60
_EMPTY_SCREEN_FPS = 2
_BLUR_RADIUS_PX = 40


def _fit_contain(src: Image.Image, screen_w: int, screen_h: int) -> Image.Image:
    fitted = src.copy()
    fitted.thumbnail((screen_w, screen_h), Image.Resampling.LANCZOS)
    return fitted


def _fit_cover(src: Image.Image, screen_w: int, screen_h: int) -> Image.Image:
    src_w, src_h = src.size
    src_ratio = src_w / src_h
    screen_ratio = screen_w / screen_h
    if src_ratio > screen_ratio:
        new_h = src_h
        new_w = int(new_h * screen_ratio)
        left = (src_w - new_w) // 2
        cropped = src.crop((left, 0, left + new_w, src_h))
    else:
        new_w = src_w
        new_h = int(new_w / screen_ratio)
        top = (src_h - new_h) // 2
        cropped = src.crop((0, top, src_w, top + new_h))
    return cropped.resize((screen_w, screen_h), Image.Resampling.LANCZOS)


def _render_image(path: Path, size: tuple[int, int], mode: str) -> pygame.Surface:
    screen_w, screen_h = size
    with Image.open(path) as img:
        src = img.convert("RGB")
        if mode == "crop":
            canvas = _fit_cover(src, screen_w, screen_h)
        elif mode == "fit":
            fitted = _fit_contain(src, screen_w, screen_h)
            canvas = Image.new("RGB", (screen_w, screen_h), color=(0, 0, 0))
            canvas.paste(
                fitted,
                ((screen_w - fitted.width) // 2, (screen_h - fitted.height) // 2),
            )
        else:
            background = _fit_cover(src, screen_w, screen_h).filter(
                ImageFilter.GaussianBlur(radius=_BLUR_RADIUS_PX)
            )
            canvas = Image.new("RGB", (screen_w, screen_h))
            canvas.paste(background, (0, 0))
            fitted = _fit_contain(src, screen_w, screen_h)
            canvas.paste(
                fitted,
                ((screen_w - fitted.width) // 2, (screen_h - fitted.height) // 2),
            )
    return pygame.image.fromstring(canvas.tobytes(), canvas.size, canvas.mode)


class SlideshowRenderer:
    """Owns the pygame display loop; reads settings from the shared runtime."""

    def __init__(self, runtime: PictureFrameRuntime, display_config: DisplayConfig) -> None:
        self._runtime = runtime
        # Retained for API compatibility; live values are read from runtime.config.
        self._config = display_config

    def _display_settings(self) -> DisplayConfig:
        return self._runtime.config.display

    def run(self) -> None:
        pygame.init()
        info = pygame.display.Info()
        native_size = (info.current_w, info.current_h)
        flags = pygame.FULLSCREEN | pygame.SCALED
        screen = pygame.display.set_mode(native_size, flags, vsync=1)
        pygame.display.set_caption("Pi Picture Frame")
        pygame.mouse.set_visible(False)

        clock = pygame.time.Clock()
        last_advance = time.time()
        last_cache_scan = 0.0
        current_path: Path | None = None
        current_surface: pygame.Surface | None = None
        previous_surface: pygame.Surface | None = None
        transition_start: float | None = None

        try:
            while not self._runtime.state.stop:
                display_settings = self._display_settings()
                slide_seconds = max(1, display_settings.slide_seconds)
                transition_seconds = max(0.0, float(display_settings.transition_seconds))

                if time.time() - last_cache_scan >= _CACHE_RESCAN_INTERVAL_S:
                    self._runtime.refresh_images()
                    last_cache_scan = time.time()

                for event in pygame.event.get():
                    if event.type == pygame.QUIT:
                        self._runtime.request_stop()
                    elif event.type == pygame.KEYDOWN:
                        if event.key in (pygame.K_ESCAPE, pygame.K_q):
                            self._runtime.request_stop()
                        elif event.key in (pygame.K_RIGHT, pygame.K_n):
                            self._runtime.state.request_next()
                        elif event.key in (pygame.K_LEFT, pygame.K_p):
                            self._runtime.state.request_previous()
                        elif event.key == pygame.K_SPACE:
                            self._runtime.state.paused = not self._runtime.state.paused

                images = self._runtime.state.images
                if not images:
                    screen.fill((0, 0, 0))
                    pygame.display.flip()
                    clock.tick(_EMPTY_SCREEN_FPS)
                    continue

                delta = self._runtime.state.consume_delta()
                should_advance = (time.time() - last_advance) >= slide_seconds
                if delta or (should_advance and not self._runtime.state.paused):
                    self._runtime.state.current_index = (
                        self._runtime.state.current_index + delta + (1 if should_advance else 0)
                    ) % len(images)
                    last_advance = time.time()

                selected = images[self._runtime.state.current_index]
                if selected != current_path:
                    new_surface = self._safe_render(selected, screen.get_size(), display_settings.mode)
                    if new_surface is not None:
                        if current_surface is not None and transition_seconds > 0:
                            previous_surface = current_surface
                            transition_start = time.time()
                        else:
                            previous_surface = None
                            transition_start = None
                        current_surface = new_surface
                        current_path = selected

                if current_surface is None:
                    screen.fill((0, 0, 0))
                elif previous_surface is not None and transition_start is not None:
                    elapsed = time.time() - transition_start
                    progress = (
                        min(1.0, elapsed / transition_seconds) if transition_seconds > 0 else 1.0
                    )
                    screen.blit(previous_surface, (0, 0))
                    faded = current_surface.copy()
                    faded.set_alpha(int(progress * 255))
                    screen.blit(faded, (0, 0))
                    if progress >= 1.0:
                        previous_surface = None
                        transition_start = None
                else:
                    screen.blit(current_surface, (0, 0))
                pygame.display.flip()
                clock.tick(
                    _TRANSITION_FRAMES_PER_SECOND
                    if transition_start is not None
                    else _IDLE_FRAMES_PER_SECOND
                )
        finally:
            pygame.quit()

    @staticmethod
    def _safe_render(path: Path, size: tuple[int, int], mode: str) -> pygame.Surface | None:
        try:
            return _render_image(path, size, mode)
        except (OSError, ValueError):
            logger.warning("Failed to render image %s", path, exc_info=True)
            return None
