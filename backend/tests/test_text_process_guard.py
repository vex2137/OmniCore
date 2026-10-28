import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def test_owned_child_stops_when_backend_parent_exits(tmp_path):
    pid_file = tmp_path / "child.pid"
    program = """
import os,sys,time,subprocess
from pathlib import Path
child=subprocess.Popen([sys.executable,'-m','omnicore.text.process_guard',str(os.getpid()),
                        sys.executable,'-c','import time; time.sleep(60)'])
Path(sys.argv[1]).write_text(str(child.pid))
time.sleep(60)
"""
    # Fixed local test program; no shell or user-controlled command text.
    parent = subprocess.Popen([sys.executable, "-c", program, str(pid_file)])  # noqa: S603
    child_pid = None
    try:
        deadline = time.monotonic() + 4
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        child_pid = int(pid_file.read_text())
        parent.terminate()
        parent.wait(timeout=3)
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            status = Path(f"/proc/{child_pid}/status")
            if not status.exists() or "State:\tZ" in status.read_text():
                break
            time.sleep(0.01)
        else:
            raise AssertionError("The owned engine remained alive after parent death")
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=3)
        if child_pid and Path(f"/proc/{child_pid}/status").exists():
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
