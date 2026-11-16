#!/bin/sh
# Explicitly invoke the AppImage's own installer; no system Python required.
set -eu
if [ "$#" -ne 1 ]; then
    echo 'Usage: install-desktop-entry.sh /absolute/path/OmniCore.AppImage' >&2
    exit 2
fi
case "$1" in /*) ;; *) echo 'Use an absolute AppImage path' >&2; exit 2 ;; esac
test -f "$1"
chmod u+x "$1"
exec "$1" --install-desktop-entry "$1"
