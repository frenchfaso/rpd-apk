# Battery reporting with incomplete telemetry

The portable Raspberry Pi battery plugin accepts standard Linux power_supply
providers. A battery need not expose capacity, charge or energy to expose useful
current, voltage and status. Missing capacity must remain unavailable, not zero.

Patch 0002-unknown-capacity.patch against pplug-batt 1.11 preserves the original
charge/energy calculation when available, supports a valid sysfs capacity as a
fallback, rejects malformed percentages and avoids division by zero. The panel
shows a neutral icon and “Percentage unavailable” while retaining charge state.
No remaining-time estimate is produced without the required charge/energy data.

Verification: `python3 tests/verify_battery_sysfs.py /path/to/patched/pplug-batt`
compiles the upstream sysfs reader against temporary fixtures, using a C compiler
and glib development files. This runs in the native APK build pipeline too.

M10 hardware telemetry remains an opt-in local experiment in the FP2 project;
it is not included in this APK and does not yet provide SOC or cell temperature.
The panel fix is useful for any standard provider with incomplete measurements.
