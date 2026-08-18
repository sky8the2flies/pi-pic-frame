import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")

from PIL import Image

from picture_frame.display import _render_image


def test_render_image_crop_mode_outputs_screen_size(tmp_path):
    path = tmp_path / "wide.jpg"
    Image.new("RGB", (400, 200), color=(120, 30, 220)).save(path)

    surface = _render_image(path, (200, 200), mode="crop")

    assert surface.get_size() == (200, 200)
