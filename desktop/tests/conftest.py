import pytest

from omnicore.desktop.api import ApiClient
from omnicore.desktop.config import DesktopConfig
from omnicore.desktop.lifecycle import BackendSession
from omnicore.desktop.window import MainWindow


@pytest.fixture
def desktop(qtbot, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("OMNICORE_DATA_DIR", raising=False)
    monkeypatch.delenv("OMNICORE_DESKTOP_URL", raising=False)
    monkeypatch.delenv("OMNICORE_DESKTOP_TOKEN", raising=False)
    api = ApiClient()
    config = DesktopConfig(ollama_enabled=False)
    session = BackendSession(api, config)
    window = MainWindow(api, session, config)

    def shutdown(_window):
        window.close()
        qtbot.waitUntil(lambda: window._allow_close, timeout=12000)

    qtbot.addWidget(window, before_close_func=shutdown)
    window.show()
    session.start()
    qtbot.waitUntil(lambda: window.is_connected and not window._health_pending, timeout=20000)
    yield window
