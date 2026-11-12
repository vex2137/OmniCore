import configparser
import hashlib
from importlib.resources import files
from pathlib import Path

import pytest

from omnicore.desktop.integration import APP_ID, desktop_exec, install


def image_file(tmp_path, name='OmniCore test "quoted" $price %done \\path.AppImage'):
    image = tmp_path / name
    image.write_bytes(b"package fixture, not executable inference")
    return image


def read_entry(path):
    config = configparser.ConfigParser(interpolation=None)
    config.optionxform = str
    config.read(path)
    return config


def test_launcher_install_preserves_identity_and_uses_own_hashed_png(tmp_path):
    image = image_file(tmp_path)
    data = tmp_path / "share"
    result = install(image, data)
    png = files("omnicore.desktop").joinpath("icon.png").read_bytes()
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert result["icon_sha256"] == hashlib.sha256(png).hexdigest()
    assert Path(result["icon"]).name == APP_ID + "-" + result["icon_sha256"] + ".png"
    assert Path(result["icon"]).read_bytes() == png
    assert Path(result["desktop"]).name == APP_ID + ".desktop"
    entry = read_entry(result["desktop"])["Desktop Entry"]
    assert entry["StartupWMClass"] == "OmniCore"
    assert entry["Exec"] == desktop_exec(image)
    assert '\\\\"' in entry["Exec"] and "\\\\$" in entry["Exec"] and "%%done" in entry["Exec"]
    assert entry["DBusActivatable"] == "false"
    assert result["launcher"] == "applications:" + APP_ID + ".desktop"
    assert image.stat().st_mode & 0o100


def test_updates_backup_preserve_custom_fields_and_do_not_touch_pins_or_data(tmp_path):
    image = image_file(tmp_path)
    data = tmp_path / "share"
    desktop = data / "applications" / (APP_ID + ".desktop")
    desktop.parent.mkdir(parents=True)
    old = (
        "[Desktop Entry]\nName=My OmniCore\nName[pl]=Moje OmniCore\nExec=old\n"
        "TryExec=gone\nActions=Docs;\n\n[Desktop Action Docs]\nName=Documentation\nExec=reader\n"
    )
    desktop.write_text(old)
    pins = tmp_path / "plasma-org.kde.plasma.desktop-appletsrc"
    pins.write_text("launchers=old,other-app")
    database = data / "omnicore" / "omnicore.db"
    database.parent.mkdir()
    database.write_bytes(b"existing history")
    result = install(image, data)
    assert Path(result["backup"]).read_text() == old
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    config = read_entry(desktop)
    assert config["Desktop Entry"]["Name[pl]"] == "Moje OmniCore"
    assert config["Desktop Action Docs"]["Exec"] == "reader"
    assert "TryExec" not in config["Desktop Entry"]
    second = install(image, data)
    assert second["backup"] is None
    assert len(list(desktop.parent.glob("*.bak-*"))) == 1
    assert pins.read_text() == "launchers=old,other-app"
    assert database.read_bytes() == b"existing history"


@pytest.mark.parametrize("kind", ["missing", "relative", "newline", "invalid-icon", "symlink"])
def test_invalid_install_does_not_replace_launcher(tmp_path, kind):
    image = image_file(tmp_path)
    data = tmp_path / "share"
    result = install(image, data)
    desktop = Path(result["desktop"])
    original = desktop.read_bytes()
    options = {}
    if kind == "missing":
        image = tmp_path / "missing.AppImage"
    elif kind == "relative":
        image = Path("relative.AppImage")
    elif kind == "newline":
        image = image_file(tmp_path, "bad\n.AppImage")
    elif kind == "invalid-icon":
        options["png"] = b"not a PNG"
    elif kind == "symlink":
        desktop.unlink()
        protected = tmp_path / "outside.desktop"
        protected.write_bytes(original)
        desktop.symlink_to(protected)
    with pytest.raises((ValueError, OSError)):
        install(image, data, **options)
    assert desktop.read_bytes() == original
