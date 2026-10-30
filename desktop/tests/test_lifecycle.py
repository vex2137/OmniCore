from PySide6.QtCore import QProcess

from omnicore.desktop.api import ApiClient
from omnicore.desktop.config import DesktopConfig
from omnicore.desktop.lifecycle import BackendSession


def test_repeated_start_reuses_the_owned_process(desktop, qtbot):
    session = desktop.session
    pid = session.process.processId()
    for _ in range(3):
        session.start()
    qtbot.waitUntil(lambda: desktop.is_connected)
    assert session.process.processId() == pid
    assert desktop.connection.text() == desktop.tr("connected")


def test_safe_stop_preserves_ownership_history_for_packaged_reports(desktop, qtbot):
    session = desktop.session
    with qtbot.waitSignal(session.stopped, timeout=12000):
        session.stop()
    assert session.process.state() == QProcess.NotRunning
    assert session.owned  # Identifies who created it, independently of process liveness.
    assert not desktop.is_connected


def test_discover_owned_server_on_random_port_without_starting_or_stopping_another(
    desktop, qtbot, monkeypatch
):
    monkeypatch.setenv("OMNICORE_DESKTOP_TOKEN", desktop.api._token)
    api = ApiClient()
    session = BackendSession(api, DesktopConfig())
    try:
        with qtbot.waitSignal(session.ready, timeout=5000):
            session.start()
        assert api.base_url == desktop.api.base_url
        assert not session.owned and session.process is None
        with qtbot.waitSignal(session.stopped):
            session.stop()
        assert desktop.session.process.state() == QProcess.Running
    finally:
        api.close()


def test_discovered_server_requires_its_token_and_never_spawns_a_duplicate(desktop, qtbot):
    api = ApiClient()
    session = BackendSession(api, DesktopConfig())
    try:
        with qtbot.waitSignal(session.failed, timeout=5000) as failure:
            session.start()
        assert failure.args == ["backend_auth_required"]
        assert session.process is None
        assert desktop.session.process.state() == QProcess.Running
    finally:
        session.stop()
        api.close()


def test_crashed_backend_can_be_started_again_with_one_click(desktop, qtbot):
    pid = desktop.session.process.processId()
    desktop.session.process.kill()
    qtbot.waitUntil(lambda: not desktop.is_connected)
    assert desktop.reconnect_button.isEnabled()
    desktop.reconnect_button.click()
    qtbot.waitUntil(lambda: desktop.is_connected and not desktop._health_pending, timeout=20000)
    assert desktop.session.process.processId() != pid


def test_failed_process_start_stops_probing_and_reports_an_error(qtbot, monkeypatch):
    import omnicore.desktop.lifecycle as lifecycle

    monkeypatch.setattr(lifecycle.sys, "executable", "/missing-omnicore-python")
    api = ApiClient()
    session = BackendSession(api, DesktopConfig())
    states = []
    session.state_changed.connect(states.append)
    try:
        with qtbot.waitSignal(session.failed, timeout=5000) as failure:
            session._spawn()
        assert failure.args == ["backend_process_error"]
        assert not session._timer.isActive()
        assert not session._starting
        assert states[-1] == "error"
    finally:
        session.stop()
        api.close()
