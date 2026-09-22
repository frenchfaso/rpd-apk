# Keyboard visibility and native terminal focus

Squeekboard's D-Bus `SetVisible` controls current visibility. Its
`org.gnome.desktop.a11y.applications screen-keyboard-enabled` preference also
controls automatic visibility when a native Wayland client enables text input.
These two states must agree when the user or orientation policy changes them.

Previously the desktop rotation daemon changed only `SetVisible` (the greeter
already changed both). With the preference false, opening LXTerminal 0.4.0
caused its VTE widget to enable text-input-v3 with terminal purpose 13, and
Squeekboard 1.43.1 hid the already-visible keyboard. No keyboard process crashed.

The rotation daemon now updates both states for desktop and greeter. Portrait
enables and shows the keyboard; landscape disables and hides it. The Raspberry Pi
panel button also updates the preference using the inverse of actual `Visible`,
so manual opening in landscape survives terminal focus, and manual closing does
not immediately reopen it on the next text-input focus. Orientation changes
between portrait and landscape still restore the orientation policy.

The small panel patch also removes an extra unref of the floating method argument
consumed by GDBus, and releases method errors. It keeps the original Raspberry Pi
button and Squeekboard, without a terminal wrapper or alternate input method.

Device diagnosis on M10, 2026-09-22:

- Preference false, SetVisible true, then launch LXTerminal: Visible becomes false.
- Preference true, SetVisible true, then launch LXTerminal: Visible stays true.
- Preference false, SetVisible false, then launch LXTerminal: Visible stays false.

The isolated diagnostic terminals were closed after each test; no desktop session
restart is needed. Installed-package and physical touch verification are recorded
in the project hardware notes.
