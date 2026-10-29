"""Linux entry point and an explicit smoke mode for the actual packaged application."""

import argparse
import json
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from omnicore.desktop.api import ApiClient
from omnicore.desktop.config import DesktopConfig, data_path
from omnicore.desktop.i18n import Translator
from omnicore.desktop.lifecycle import BackendSession
from omnicore.desktop.platforms import configure_platform
from omnicore.desktop.window import MainWindow


class SmokeRun:
    """Drive real widgets and HTTP/SSE. A real model is required only with --smoke-gguf."""

    def __init__(self, app, window, output, screenshot, gguf):
        self.app, self.window = app, window
        self.output, self.screenshot, self.gguf = output, screenshot, gguf
        self.stage = "connecting"
        self.finished = False
        self.ok = False
        self.record = None
        self.pid = None
        self.timer = QTimer(window)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)
        window.connected.connect(self.connected)
        self.timer.start()
        QTimer.singleShot(180000 if gguf else 40000, self.timeout)
        app.aboutToQuit.connect(self.report)

    def connected(self):
        if self.stage != "connecting":
            return
        process = self.window.session.process
        self.pid = process.processId() if process else None
        if self.gguf:
            self.stage = "import"
            self.window.import_gguf(self.gguf)
        else:
            self.stage = "ready"
            QTimer.singleShot(500, self.complete)

    def tick(self):
        w = self.window
        if self.stage == "import" and w.models:
            record = next(
                (r for r in w.models if r["location"] == str(Path(self.gguf).absolute())), None
            )
            if record:
                w.engine_filter.setCurrentText("llama.cpp")
                for row in range(w.model_table.rowCount()):
                    if w.model_table.item(row, 0).data(Qt.UserRole) == record["id"]:
                        w.model_table.selectRow(row)
                self.stage = "load"
                w.load_model()
        elif self.stage == "load" and any(
            r["compatibility"] in {"load_verified", "tested"} for r in w.models
        ):
            self.stage = "conversation"
            w.new_conversation()
        elif self.stage == "conversation" and w.current_id:
            self.stage = "generating"
            w.composer.setPlainText("Write a short welcome to OmniCore, a local AI application.")
            w.send_message()
        elif self.stage == "generating" and w.last_job and not w.active_job:
            self.record = w.last_job
            if self.record["state"] != "completed" or not self.record["content"].strip():
                self.timeout()
                return
            self.stage = "history"
            w.refresh_messages()
        elif self.stage == "history" and any(m["role"] == "assistant" for m in w.messages):
            self.complete()

    def complete(self):
        if self.finished:
            return
        self.finished = True
        self.ok = self.window.is_connected
        if self.screenshot:
            self.screenshot.parent.mkdir(parents=True, exist_ok=True)
            self.ok = self.window.grab().save(str(self.screenshot)) and self.ok
        self.window.close()

    def timeout(self):
        if not self.finished:
            self.finished = True
            self.ok = False
            self.window.close()

    def report(self):
        if self.output:
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text(
                json.dumps(
                    {
                        "ok": self.ok,
                        "stage": self.stage,
                        "backend_pid": self.pid,
                        "owned": self.window.session.owned,
                        "locale": self.window.config.locale,
                        "theme": self.window.config.theme,
                        "real_gguf": bool(self.gguf),
                        "generation": self.record,
                        "models": len(self.window.models),
                        "conversations": len(self.window.conversations),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            )


def main():
    parser = argparse.ArgumentParser(description="OmniCore native Linux desktop")
    parser.add_argument("--smoke-output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--smoke-gguf", type=Path)
    args = parser.parse_args()
    if configure_platform() is None:
        print("OmniCore needs a graphical session: DISPLAY or WAYLAND_DISPLAY.", file=sys.stderr)
        return 1
    app = QApplication(sys.argv[:1])
    app.setApplicationName("OmniCore")
    app.setOrganizationName("OmniCore")
    app.setDesktopFileName("io.github.vex2137.OmniCore")
    app.setStyle("Fusion")
    from importlib.resources import files

    icon_path = files("omnicore.desktop").joinpath("icon.svg")
    app.setWindowIcon(QIcon(str(icon_path)))
    try:
        config = DesktopConfig.load()
    except (OSError, ValueError, TypeError):
        QMessageBox.critical(None, "OmniCore", Translator("pl-PL")("config_error"))
        return 1
    if args.smoke_gguf:
        config.model_roots = [str(args.smoke_gguf.absolute().parent)]
        config.ollama_enabled = False
        config.parameters = {"max_tokens": 48, "context_size": 512, "temperature": 0}
    data_path().mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = QLockFile(str(data_path() / "desktop.lock"))
    if not lock.tryLock(0):
        QMessageBox.warning(None, "OmniCore", Translator(config.locale)("already_running"))
        return 1
    api = ApiClient()
    session = BackendSession(api, config)
    window = MainWindow(api, session, config)
    smoke = (
        SmokeRun(app, window, args.smoke_output, args.screenshot, args.smoke_gguf)
        if args.smoke_output
        else None
    )
    window.show()
    QTimer.singleShot(0, session.start)
    result = app.exec()
    lock.unlock()
    return (0 if smoke.ok else 1) if smoke else result


if __name__ == "__main__":
    raise SystemExit(main())
