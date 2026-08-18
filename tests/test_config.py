from pathlib import Path

from picture_frame.config import AppConfig, load_config, save_config


def test_config_from_dict_defaults_immich():
    raw = {
        "immich": {
            "base_url": "http://pi.local:2283/",
            "api_key": "abc",
            "albums": ["album-1"],
        },
        "cache": {
            "directory": "./data/cache",
            "metadata_file": "./data/cache/metadata.json",
        },
    }

    config = AppConfig.from_dict(raw, base_dir=Path("/tmp"))

    assert config.immich.base_url == "http://pi.local:2283"
    assert config.immich.api_key == "abc"
    assert config.immich.albums == ["album-1"]
    assert config.cache.max_disk_usage_percent == 80


def test_config_round_trip_persists(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[immich]
base_url = "http://localhost:2283"
api_key = ""
albums = []

[cache]
directory = "./cache"
metadata_file = "./cache/metadata.json"
""".strip()
    )

    config = load_config(config_path)
    config.immich.api_key = "new-key"
    config.immich.albums = ["album-42"]
    save_config(config_path, config)

    reloaded = load_config(config_path)
    assert reloaded.immich.api_key == "new-key"
    assert reloaded.immich.albums == ["album-42"]
