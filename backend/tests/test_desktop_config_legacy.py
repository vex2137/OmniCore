import json

from omnicore.desktop.config import DesktopConfig


def test_legacy_desktop_config_loads_without_losing_supported_preferences(tmp_path):
    path = tmp_path / "desktop.json"
    payload = {
        "locale": "en-US",
        "theme": "dark",
        "lan_enabled": True,
        "history_width": 280,
        "auto_start_backend": True,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    config = DesktopConfig.load(path)

    assert config.locale == "en-US"
    assert config.theme == "dark"
    assert not hasattr(config, "lan_enabled")
