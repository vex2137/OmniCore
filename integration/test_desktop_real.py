"""Explicit real Qt + HTTP/SSE + GGUF test. No mocked inference or automatic weights."""

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer
from PySide6.QtWidgets import QApplication

from omnicore.desktop.api import ApiClient
from omnicore.desktop.config import DesktopConfig
from omnicore.desktop.lifecycle import BackendSession
from omnicore.desktop.window import MainWindow


def test_real_gui_stream_cancel_history_restart(qtbot, tmp_path, monkeypatch):
    model = Path(os.environ["OMNICORE_TEST_GGUF"]).resolve(strict=True)
    engine = Path(os.environ["OMNICORE_TEST_LLAMA_SERVER"]).resolve(strict=True)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("OMNICORE_DATA_DIR", raising=False)
    monkeypatch.delenv("OMNICORE_DESKTOP_URL", raising=False)
    config = DesktopConfig(
        llama_server=str(engine),
        model_roots=[str(model.parent)],
        ollama_enabled=False,
        parameters={"max_tokens": 48, "context_size": 512, "temperature": 0},
    )
    api = ApiClient()
    session = BackendSession(api, config)
    w = MainWindow(api, session, config)

    def shutdown(_):
        w.close()
        qtbot.waitUntil(lambda: w._allow_close, timeout=12000)

    qtbot.addWidget(w, before_close_func=shutdown)
    w.show()
    session.start()
    qtbot.waitUntil(lambda: w.is_connected and not w._health_pending, timeout=20000)
    w.import_gguf(str(model))
    qtbot.waitUntil(lambda: len(w.models) == 1)
    w.model_table.selectRow(0)
    w.load_model()
    qtbot.waitUntil(
        lambda: w.models[0]["compatibility"] in {"load_verified", "tested"}, timeout=130000
    )
    assert w.models[0]["compatibility"] in {"load_verified", "tested"}
    w.new_conversation()
    qtbot.waitUntil(lambda: bool(w.current_id))
    conversation = w.current_id
    w.composer.setPlainText("Write a friendly welcome to a local AI application.")
    snapshots = []
    api.snapshot.connect(snapshots.append)
    ticks = []
    timer = QTimer()
    timer.setInterval(20)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    qtbot.mouseClick(w.send_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: bool(w.last_job) and not w.active_job, timeout=130000)
    assert w.last_job["state"] == "completed" and w.last_job["content"].strip()
    qtbot.waitUntil(lambda: any(m["role"] == "assistant" for m in w.messages))
    assert len(snapshots) > 2 and any(r["state"] == "running" for r in snapshots)
    assert len(ticks) > 5  # The main Qt loop remained live during actual inference.
    timer.stop()
    answer = w.last_job["content"]
    w.copy_answer()
    assert QApplication.clipboard().text() == answer
    w.config.parameters["max_tokens"] = 1024
    w.composer.setPlainText("Count from one to one hundred, explaining every number in detail.")
    w.send_message()
    qtbot.waitUntil(lambda: bool(w.active_job) and bool(w.last_job.get("content")), timeout=130000)
    w.stop_generation()
    qtbot.waitUntil(lambda: not w.active_job, timeout=12000)
    assert w.last_job["state"] == "cancelled"
    qtbot.waitUntil(lambda: any(m.get("status") == "cancelled" for m in w.messages))
    w.is_connected = False
    session.restart(w.config)
    qtbot.waitUntil(lambda: w.is_connected and not w._health_pending, timeout=20000)
    w.open_conversation(conversation)
    qtbot.waitUntil(lambda: any(m["content"] == answer for m in w.messages))
    # Close during a third actual generation, then reopen persisted history.
    w.composer.setPlainText("Describe the numbers from one to one hundred in detail.")
    w.send_message()
    qtbot.waitUntil(lambda: bool(w.active_job) and bool(w.last_job.get("content")), timeout=130000)
    backend_pid = session.process.processId()
    children = subprocess.check_output(  # noqa: S603,S607 — inspect only this owned backend.
        ["/usr/bin/ps", "--ppid", str(backend_pid), "-o", "pid="], text=True
    ).split()
    assert Path(f"/proc/{backend_pid}/status").is_file()
    assert children, "The owned backend must have a real engine child"
    w.close()
    qtbot.waitUntil(lambda: w._allow_close, timeout=12000)
    assert session.process.state() == QProcess.NotRunning
    qtbot.waitUntil(
        lambda: all(not Path(f"/proc/{pid}").exists() for pid in children), timeout=10000
    )
    from omnicore.database import Database
    from omnicore.desktop.config import data_path
    from omnicore.text.conversations import Conversations
    from omnicore.text.store import TextStore

    saved = Conversations(TextStore(Database(data_path()))).messages(conversation)
    assert any(m.content == answer and m.status == "completed" for m in saved)
    assert saved[-1].status == "cancelled" and saved[-1].content
