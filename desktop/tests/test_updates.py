import json

import httpx
import pytest
from PySide6.QtCore import Qt

from omnicore.desktop import updates
from omnicore.desktop.config import DesktopConfig
from omnicore.desktop.i18n import Translator


def release(tag, **values):
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": "-" in tag,
        "html_url": updates.RELEASE_PREFIX + tag,
        "body": "Release notes",
        **values,
    }


@pytest.mark.parametrize(
    ("channel", "expected"), [("stable", "0.2.0"), ("rc", "0.3.0-rc.2"), ("beta", "0.4.0-beta.10")]
)
def test_channel_order_and_normalized_versions(channel, expected):
    records = [
        release(tag)
        for tag in ("v0.2.0", "v0.3.0-rc.2", "v0.4.0-beta.2", "v0.4.0-beta.10", "v0.5.0-alpha.1")
    ]
    assert updates.select_update(records, "0.2.0-beta.3", channel).version == expected
    assert updates.select_update([release("v0.2.0-beta.3")], "0.2.0b3", "beta") is None


def test_untrusted_release_links_drafts_and_invalid_metadata_are_ignored():
    records = [
        release("v9.0.0", draft=True),
        release("v8.0.0", html_url="https://evil.invalid/"),
        release("v7.0.0", html_url=updates.RELEASE_PREFIX + "../other"),
        release("v6.0.0", prerelease=True),
        release("not-a-version"),
        None,
        release("v0.1.0"),
    ]
    assert updates.select_update(records, "0.2.0b3", "beta") is None
    assert updates.select_update([], "0.2.0b3", "beta") is None
    with pytest.raises(ValueError):
        updates.select_update({}, "0.2.0b3", "beta")


def test_fetch_uses_public_list_without_backend_credentials(monkeypatch):
    # Ignore proxy settings solely for the isolated HTTP transport in this test.
    monkeypatch.delenv("HTTP_PROXY", raising=False)
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=[release("v0.2.0-beta.4")])

    result = updates.fetch_update("0.2.0b3", "beta", transport=httpx.MockTransport(handler))
    assert result.version == "0.2.0-beta.4"
    assert seen[0].url.path.endswith("/releases")
    assert seen[0].url.params["per_page"] == "100"
    assert "authorization" not in seen[0].headers


@pytest.mark.parametrize("status", [404, 200])
def test_no_published_releases_is_not_an_error(status):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, json=[]))
    assert updates.fetch_update("0.2.0b3", "stable", transport=transport) is None


@pytest.mark.parametrize(
    "status,body,error",
    [
        (403, b"{}", httpx.HTTPStatusError),
        (200, b"not-json", ValueError),
        (200, b"x" * 2_000_001, ValueError),
    ],
)
def test_network_and_bounded_response_errors(status, body, error):
    transport = httpx.MockTransport(lambda request: httpx.Response(status, content=body))
    with pytest.raises(error):
        updates.fetch_update("0.2.0b3", "stable", transport=transport)


def test_update_panel_runs_off_main_thread_and_persists_channel(qtbot, tmp_path, monkeypatch):
    import threading

    main_thread = threading.get_ident()
    worker_threads = []
    config = DesktopConfig(update_channel="stable")
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(config, "save", lambda: DesktopConfig.save(config, path))

    def fetch(current, channel):
        worker_threads.append(threading.get_ident())
        return updates.Update("0.3.0", updates.RELEASE_PREFIX + "v0.3.0", "<b>Plain text</b>")

    monkeypatch.setattr(updates, "fetch_update", fetch)
    panel = updates.UpdatePanel(config, Translator("pl-PL"))
    qtbot.addWidget(panel)
    panel.show()
    panel.channel.setCurrentIndex(1)
    assert json.loads(path.read_text())["update_channel"] == "beta"
    qtbot.mouseClick(panel.check, Qt.LeftButton)
    qtbot.waitUntil(lambda: not panel._busy)
    assert worker_threads and main_thread not in worker_threads
    assert "0.3.0" in panel.status.text()
    assert panel.notes.toPlainText() == "<b>Plain text</b>"
    opened = []
    monkeypatch.setattr(
        updates.QDesktopServices, "openUrl", lambda url: opened.append(url.toString())
    )
    qtbot.mouseClick(panel.open, Qt.LeftButton)
    assert opened == [updates.RELEASE_PREFIX + "v0.3.0"]
    panel.retranslate(Translator("en-US"))
    assert panel.check.text() == "Check for updates"
    panel.channel.setCurrentIndex(0)
    assert panel.update is None and panel.open.isHidden()


def test_update_panel_recovers_from_network_error(qtbot, monkeypatch):
    def fail(*args):
        raise httpx.ConnectError("private connection details")

    monkeypatch.setattr(updates, "fetch_update", fail)
    panel = updates.UpdatePanel(DesktopConfig(), Translator("en-US"))
    qtbot.addWidget(panel)
    panel.start_check()
    qtbot.waitUntil(lambda: not panel._busy)
    assert panel.check.isEnabled() and panel.channel.isEnabled()
    assert "Cannot check" in panel.status.text()
    assert "private" not in panel.status.text()
    assert panel.open.isHidden()


def test_beta_build_defaults_to_beta_channel_and_preserves_saved_choice(tmp_path):
    assert DesktopConfig().update_channel == "beta"
    path = tmp_path / "desktop.json"
    DesktopConfig(update_channel="stable").save(path)
    assert DesktopConfig.load(path).update_channel == "stable"
