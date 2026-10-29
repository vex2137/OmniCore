"""Single bundled executable entry point, including headless child modes."""

import ctypes
import os
import signal
import sys


def protect_parent(expected):
    if sys.platform != "linux":
        raise RuntimeError("The desktop process supervisor requires Linux")
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Cannot protect child process")
    if os.getppid() != expected:
        raise SystemExit("Desktop parent exited during startup")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--hardware-test":
        sys.argv.pop(1)
        from omnicore.hardware_acceptance import main as acceptance

        raise SystemExit(acceptance())
    if len(sys.argv) > 1 and sys.argv[1] == "--engine-guard":
        from omnicore.text.process_guard import main as guard

        sys.argv.pop(1)
        guard()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--backend":
        sys.argv.pop(1)
        expected = int(sys.argv.pop(1))
        protect_parent(expected)
        from omnicore.cli import main as backend

        backend()
        return
    from omnicore.desktop.main import main as desktop

    raise SystemExit(desktop())


if __name__ == "__main__":
    main()
