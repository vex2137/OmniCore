"""Linux child bootstrap: terminate an owned engine if its backend parent dies."""

import ctypes
import os
import signal
import sys


def main():
    if sys.platform != "linux" or len(sys.argv) < 3:
        raise SystemExit("The owned engine guard requires Linux and an executable")
    expected_parent = int(sys.argv[1])
    libc = ctypes.CDLL(None, use_errno=True)
    prctl = libc.prctl
    prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    prctl.restype = ctypes.c_int
    if prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
        raise OSError(ctypes.get_errno(), "Cannot protect engine lifecycle")
    if os.getppid() != expected_parent:
        raise SystemExit("Backend parent exited during engine startup")
    from omnicore.text.native import native_environment

    os.execve(sys.argv[2], sys.argv[2:], native_environment())  # noqa: S606 — configured trusted executable, no shell.


if __name__ == "__main__":
    main()
