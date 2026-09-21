#!/bin/sh
# Native compositor/panel/file-manager smoke test, using no physical display.
set -eu
if [ "${RPD_HEADLESS_ENV:-0}" != 1 ]; then
    export XDG_RUNTIME_DIR=$(mktemp -d)
    export HOME=$(mktemp -d)
    export RPD_HEADLESS_ENV=1
    exec dbus-run-session -- sh "$0"
fi
export WLR_BACKENDS=headless WLR_RENDERER=pixman WLR_HEADLESS_OUTPUTS=1
export LIBGL_ALWAYS_SOFTWARE=1
# Nested image-loader user namespaces are unavailable in the CI container.
# This affects only the disposable graphical test, never installed sessions.
export GLYCIN_DISABLE_SANDBOX=i-know-the-risks
cleanup() {
    trap - EXIT INT TERM
    [ -z "${compositor_pid:-}" ] || kill "$compositor_pid" 2>/dev/null || :
    [ -z "${session_pid:-}" ] || kill "$session_pid" 2>/dev/null || :
    rm -rf "$XDG_RUNTIME_DIR" "$HOME" 2>/dev/null || :
}
trap cleanup EXIT INT TERM
mkdir -p "$HOME/.config/autostart"
cat > "$HOME/.config/autostart/rpd-smoke.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Session smoke marker
Exec=touch $HOME/autostart-passed
EOF
rpd-session > /tmp/rpd-headless.log 2>&1 &
session_pid=$!
export WAYLAND_DISPLAY=wayland-0
for attempt in $(seq 1 30); do
    [ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ] && break
    kill -0 "$session_pid"
    sleep 1
done
[ -S "$XDG_RUNTIME_DIR/$WAYLAND_DISPLAY" ]
compositor_pid=$session_pid
export LABWC_PID=$compositor_pid
sleep 5
for name in labwc wf-panel-pi pcmanfm squeekboard; do
    ps -eo stat,comm | awk -v name="$name" '$2 == name && $1 !~ /^Z/ { found=1 } END { exit !found }' || { cat /tmp/rpd-headless.log; echo "Missing running process: $name" >&2; exit 1; }
done
test -f "$HOME/autostart-passed"
for directory in DESKTOP DOWNLOAD DOCUMENTS MUSIC PICTURES VIDEOS; do
    location=$(xdg-user-dir "$directory")
    [ "$location" != "$HOME" ] && [ -d "$location" ]
done
printf 'trash round-trip\n' > "$HOME/rpd-trash-smoke"
gio trash "$HOME/rpd-trash-smoke"
test ! -e "$HOME/rpd-trash-smoke"
test -f "$HOME/.local/share/Trash/files/rpd-trash-smoke"
gio list trash:/// | grep -q rpd-trash-smoke
gio trash --empty
# Exercise the shipped applications without invoking any power actions.
pcmanfm "$(xdg-user-dir DOCUMENTS)" &
sleep 2
grim /tmp/rpd-headless.png
gdbus call --session --dest sm.puri.OSK0 --object-path /sm/puri/OSK0 --method sm.puri.OSK0.SetVisible true
gdbus call --session --dest sm.puri.OSK0 --object-path /sm/puri/OSK0 --method org.freedesktop.DBus.Properties.Get sm.puri.OSK0 Visible | grep -q true
sleep 1
grim /tmp/rpd-keyboard.png
if grep -E 'error loading widget|symbol lookup error|Segmentation fault' /tmp/rpd-headless.log; then exit 1; fi
labwc --exit
wait "$session_pid"
session_pid=
compositor_pid=
printf 'Native headless Wayland, panel, file manager and keyboard smoke passed\n'
