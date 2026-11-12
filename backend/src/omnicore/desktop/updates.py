"""Manual, asynchronous public release checks; never forwards the backend token."""

import re
import time
from dataclasses import dataclass

import httpx
from packaging.version import Version
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QPlainTextEdit, QPushButton, QWidget

from omnicore.release import distribution_version

ENDPOINT = "https://api.github.com/repos/vex2137/OmniCore/releases"
RELEASE_PREFIX = "https://github.com/vex2137/OmniCore/releases/tag/"
TAG = re.compile(r"v?(\d+\.\d+\.\d+(?:-(?:beta|rc)\.\d+)?)\Z")


@dataclass(frozen=True)
class Update:
    version: str
    url: str
    notes: str


def select_update(releases, current, channel):
    if channel not in {"stable", "beta", "rc"} or not isinstance(releases, list):
        raise ValueError("Invalid release data")
    installed = Version(current)
    candidates = []
    for record in releases[:100]:
        if not isinstance(record, dict) or record.get("draft") is not False:
            continue
        tag = record.get("tag_name", "")
        match = TAG.fullmatch(tag) if isinstance(tag, str) else None
        if not match:
            continue
        version = Version(match[1])
        stage = version.pre[0] if version.pre else None
        if bool(record.get("prerelease")) != bool(stage):
            continue
        if stage and (channel == "stable" or (channel == "rc" and stage != "rc")):
            continue
        if version <= installed or record.get("html_url") != RELEASE_PREFIX + tag:
            continue
        notes = record.get("body")
        candidates.append(
            (
                version,
                Update(
                    match[1], RELEASE_PREFIX + tag, notes[:6000] if isinstance(notes, str) else ""
                ),
            )
        )
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def fetch_update(current, channel, *, transport=None):
    # Separate HTTP client, fixed HTTPS origin, no Authorization or URL from API data.
    started = time.monotonic()
    with httpx.Client(timeout=8, follow_redirects=False, transport=transport) as client:
        with client.stream(
            "GET",
            ENDPOINT,
            params={"per_page": 100},
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "OmniCore-update-check",
            },
        ) as response:
            if response.status_code == 404:
                return None
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > 2_000_000 or time.monotonic() - started > 15:
                    raise ValueError("Release response exceeded limits")
    import json

    return select_update(json.loads(body), current, channel)


class CheckSignals(QObject):
    finished = Signal(object, bool)


class CheckWorker(QRunnable):
    def __init__(self, channel):
        super().__init__()
        self.channel = channel
        self.signals = CheckSignals()

    def run(self):
        try:
            update = fetch_update(distribution_version(), self.channel)
        except (httpx.HTTPError, ValueError):
            self.signals.finished.emit(None, True)
        else:
            self.signals.finished.emit(update, False)


class UpdatePanel(QWidget):
    def __init__(self, config, tr, parent=None):
        super().__init__(parent)
        self.config, self.tr = config, tr
        self.update = None
        self._status_key = "updates_hint"
        self._busy = False
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.title = QLabel()
        self.current = QLabel()
        self.current.setTextFormat(Qt.PlainText)
        self.channel_label = QLabel()
        self.channel = QComboBox()
        for key in ("stable", "beta", "rc"):
            self.channel.addItem({"stable": "Stable", "beta": "Beta", "rc": "RC"}[key], key)
        self.channel.setCurrentIndex(self.channel.findData(config.update_channel))
        self.channel.currentIndexChanged.connect(self.change_channel)
        self.status = QLabel()
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(160)
        self.notes.hide()
        self.check = QPushButton()
        self.check.clicked.connect(self.start_check)
        self.open = QPushButton()
        self.open.clicked.connect(self.open_release)
        self.open.hide()
        layout.addRow(self.title)
        layout.addRow(self.current)
        layout.addRow(self.channel_label, self.channel)
        layout.addRow(self.status)
        layout.addRow(self.notes)
        layout.addRow(self.check, self.open)
        self.retranslate(tr)

    def retranslate(self, tr):
        self.tr = tr
        self.title.setText(tr("updates"))
        self.current.setText(tr("updates_current", version=distribution_version()))
        self.channel_label.setText(tr("updates_channel"))
        self.check.setText(tr("updates_check"))
        self.open.setText(tr("updates_open"))
        self.status.setText(
            tr(self._status_key, version=self.update.version if self.update else "")
        )

    def change_channel(self):
        self.config.update_channel = self.channel.currentData()
        self.config.save()
        self.update = None
        self.notes.hide()
        self.open.hide()
        self._status_key = "updates_hint"
        self.retranslate(self.tr)

    def start_check(self):
        if self._busy:
            return
        self._busy = True
        self.check.setEnabled(False)
        self.channel.setEnabled(False)
        self.update = None
        self.notes.hide()
        self.open.hide()
        self._status_key = "updates_checking"
        self.retranslate(self.tr)
        self._worker = CheckWorker(self.channel.currentData())
        self._worker.signals.finished.connect(self.received)
        QThreadPool.globalInstance().start(self._worker)

    def received(self, update, failed):
        self._busy = False
        self.check.setEnabled(True)
        self.channel.setEnabled(True)
        self.update = update
        self._status_key = (
            "updates_error" if failed else "updates_available" if update else "updates_none"
        )
        self.notes.setPlainText(update.notes if update else "")
        self.notes.setVisible(bool(update and update.notes))
        self.open.setVisible(update is not None)
        self.retranslate(self.tr)

    def open_release(self):
        if self.update and self.update.url.startswith(RELEASE_PREFIX):
            QDesktopServices.openUrl(QUrl(self.update.url))
