#!/bin/sh
# Exercise the real LightDM protocol and greeter without logging in or touching a seat.
set -eu
# This script runs only in the disposable build container, after the desktop test.
cleanup() {
    [ -z "${manager:-}" ] || kill "$manager" 2>/dev/null || :
    for name in pi-greeter squeekboard labwc; do pkill -u builder -x "$name" 2>/dev/null || :; done
}
trap cleanup EXIT INT TERM
cleanup
rm -rf /tmp/rpd-greeter-test
mkdir -p /tmp/rpd-greeter-test/runtime /tmp/rpd-greeter-test/entries
chown builder:builder /tmp/rpd-greeter-test/runtime
chmod 700 /tmp/rpd-greeter-test/runtime
cat > /tmp/rpd-greeter-test/start <<'EOF'
#!/bin/sh
export XDG_RUNTIME_DIR=/tmp/rpd-greeter-test/runtime
export WLR_BACKENDS=headless WLR_HEADLESS_OUTPUTS=1 WLR_RENDERER=pixman
export LIBGL_ALWAYS_SOFTWARE=1 GLYCIN_DISABLE_SANDBOX=i-know-the-risks
exec /usr/bin/rpd-greeter-session
EOF
chmod 755 /tmp/rpd-greeter-test/start
cat > /tmp/rpd-greeter-test/entries/test.desktop <<'EOF'
[Desktop Entry]
Name=RPD greeter test
Exec=/tmp/rpd-greeter-test/start
Type=Application
X-LightDM-Session-Type=wayland
EOF
cat > /tmp/rpd-greeter-test/lightdm.conf <<'EOF'
[LightDM]
run-directory=/tmp/rpd-greeter-test/run
cache-directory=/tmp/rpd-greeter-test/cache
log-directory=/tmp/rpd-greeter-test/log
logind-check-graphical=false
greeters-directory=/tmp/rpd-greeter-test/entries
greeter-user=builder
minimum-vt=0
[Seat:*]
greeter-session=test
user-session=rpd-session
allow-guest=false
EOF
timeout 20 lightdm --test-mode --debug --config=/tmp/rpd-greeter-test/lightdm.conf > /tmp/greeter-test.log 2>&1 &
manager=$!
sleep 8
grep -q 'Greeter connected' /tmp/greeter-test.log
grep -q 'Prompt greeter with' /tmp/greeter-test.log
pid=$(pgrep -n -x pi-greeter)
address=$(su builder -c "cat /proc/$pid/environ" | tr '\0' '\n' | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
[ -n "$address" ]
# Hide any automatic focus-triggered keyboard, then prove tapping reopens it.
su builder -c "DBUS_SESSION_BUS_ADDRESS='$address' gdbus call --session --dest sm.puri.OSK0 --object-path /sm/puri/OSK0 --method sm.puri.OSK0.SetVisible false"
sleep 1
su builder -c "DBUS_SESSION_BUS_ADDRESS='$address' gdbus call --session --dest sm.puri.OSK0 --object-path /sm/puri/OSK0 --method org.freedesktop.DBus.Properties.Get sm.puri.OSK0 Visible" | grep -q false
# Real pointer events exercise GTK's release handler and normal focus behaviour.
su builder -c 'export XDG_RUNTIME_DIR=/tmp/rpd-greeter-test/runtime WAYLAND_DISPLAY=wayland-0; wlrctl pointer move -2000 -2000; wlrctl pointer move 700 360; wlrctl pointer click left'
sleep 2
su builder -c "DBUS_SESSION_BUS_ADDRESS='$address' gdbus call --session --dest sm.puri.OSK0 --object-path /sm/puri/OSK0 --method org.freedesktop.DBus.Properties.Get sm.puri.OSK0 Visible" | grep -q true
# Press a harmless test character on Squeekboard; never submit the login form.
su builder -c 'export XDG_RUNTIME_DIR=/tmp/rpd-greeter-test/runtime WAYLAND_DISPLAY=wayland-0; wlrctl pointer move -2000 -2000; wlrctl pointer move 60 410; wlrctl pointer click left'
sleep 1
if [ -S /tmp/rpd-greeter-test/runtime/wayland-0 ]; then
su builder -c 'XDG_RUNTIME_DIR=/tmp/rpd-greeter-test/runtime WAYLAND_DISPLAY=wayland-0 grim /tmp/rpd-greeter-test.png'
cp /tmp/rpd-greeter-test.png /work/out/
fi
kill "$manager" 2>/dev/null || :
wait "$manager" || :
cleanup
trap - EXIT INT TERM
cp /tmp/greeter-test.log /work/out/lightdm-test.log
printf 'LightDM greeter protocol, PAM prompt and visible on-screen keyboard passed\n' >> /work/out/validation.txt
