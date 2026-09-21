# Convertible display rotation

`rpd-autorotate` connects the standard `net.hadess.SensorProxy` D-Bus interface to wlroots output transforms and Squeekboard. `rpd-desktop-m10` installs the package and the board output/mapping in `/etc/xdg/rpd/autorotate.conf`. It runs inside the RPD graphical session; the greeter does not rotate.

The M10 uses its existing qcom-smgr-accel kernel driver. No gyroscope, new kernel, raw input permissions or polkit override is needed. Normal, left-up, bottom-up and right-up map to normal, 90, 180 and 270 respectively. Hardware mapping remains in the M10 profile; the daemon/policy are reusable.

A new orientation must persist for 0.8 seconds. Flat/undefined readings cancel a pending turn. On entering portrait Squeekboard is shown; on entering landscape it is hidden. Changes within the same aspect (for example upside-down portrait) preserve manual keyboard visibility. The panel button still works. The daemon does not poll or continually force the current transform; a manual Screens/profile change is retained until a subsequent sensor orientation change. A display rotation changes only the configured output transform, preserving its mode, scale and position; the configured touchscreen is explicitly mapped to that output, allowing wlroots 0.20 to rotate touch events automatically. Its base calibration stays constant: applying an additional rotation matrix would rotate events twice. Other input devices and desktop settings are preserved. The session ensures this mapping before starting the compositor.

```sh
rpd-autorotate --disable  # keep the current orientation; stop claiming the sensor
rpd-autorotate --enable
rpd-autorotate --status
```

These settings persist per user. Advanced mapping/delay overrides can be placed in `~/.config/rpd/autorotate.conf`. The daemon releases its sensor claim on session deactivation, screen lock, disable or exit. Display blanking alone currently does not release the claim; the independent blanking setting is disabled by default on M10. Physical suspend/power consumption is not qualified by policy unit tests.

Systemd starts the controller through the session's XDG autostart runner and binds it to `rpd-session.target`; the non-systemd path runs as a supervised autostart child. The native ARM package tests cover debounce, jitter, flat-state cancellation and preservation of manual keyboard choices. Actual device orientation/touch verification is recorded in the main FP2 project device notes, separately from CI.

Sensor API: https://hadess.pages.freedesktop.org/iio-sensor-proxy/gdbus-net.hadess.SensorProxy.html

Touch rotation requires wlroots 0.20. The M10 profile targets only `Goodix Capacitive TouchScreen`; `touch_matrix` supplies constant base calibration. The labwc manual currently suggests calibrationMatrix for rotation, but wlroots 0.20 already transforms events for a mapped output in `types/wlr_cursor.c` (`handle_touch_down` and `handle_touch_motion`). Source: https://gitlab.freedesktop.org/wlroots/wlroots/-/blob/0.20.0/types/wlr_cursor.c
