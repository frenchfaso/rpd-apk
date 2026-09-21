#!/bin/sh
# Native compositor/panel/file-manager smoke test, using no physical display.
set -eu
export XDG_RUNTIME_DIR
XDG_RUNTIME_DIR=$(mktemp -d)
export HOME
HOME=$(mktemp -d)
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1
export LIBGL_ALWAYS_SOFTWARE=1
# Nested image-loader user namespaces are unavailable in the CI container.
# This affects only the disposable graphical test, never installed sessions.
export GLYCIN_DISABLE_SANDBOX=i-know-the-risks
cleanup() {
    trap - EXIT INT TERM
    [ -z "${compositor_pid:-}" ] || kill "$compositor_pid" 2>/dev/null || :
    [ -z "${session_pid:-}" ] || kill "$session_pid" 2>/dev/null || :
    rm -rf "$XDG_RUNTIME_DIR" "$HOME"
}
trap cleanup EXIT INT TERM
rpd-session > /tmp/rpd-headless.log 2>&1 &
session_pid=$!
export WAYLAND_DISPLAY=wayland-0
for attempt in $(seq 1 30); do
    [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && break
    kill -0 "$session_pid"
    sleep 1
done
[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]
compositor_pid=$(pgrep -P "$session_pid" -x labwc)
export LABWC_PID=$compositor_pid
sleep 5
for name in labwc wf-panel-pi pcmanfm squeekboard; do
    ps -eo stat,comm | awk -v name="$name" '$2 == name && $1 !~ /^Z/ { found=1 } END { exit !found }' || { cat /tmp/rpd-headless.log; echo "Missing running process: $name" >&2; exit 1; }
done
grim /tmp/rpd-headless.png
if grep -E 'error loading widget|symbol lookup error|Segmentation fault' /tmp/rpd-headless.log; then exit 1; fi
labwc --exit
wait "$session_pid"
session_pid=
compositor_pid=
printf 'Native headless Wayland, panel, file manager and keyboard smoke passed\n'
