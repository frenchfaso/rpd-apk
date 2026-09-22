# Battery telemetry and estimates

The desktop uses the official Raspberry Pi `pplug-batt` panel plugin. Its standard
Linux power_supply reader remains primary. Our small patches preserve unknown
capacity as unknown, accept valid kernel percentages, and add clearly labelled
userspace estimates only when hardware capacity is unavailable. Fresh native
capacity always takes precedence; estimates older than 90 seconds are ignored.

## M10 support

`rpd-desktop-m10` includes `rpd-power`, which pulls in `rpd-battery-m10`.
The latter is built alongside the backlight/OTG modules against the exact official
kernel and export metadata, with no dependency that pins the kernel package.
The scheduled kernel update workflow rebuilds all modules. A mismatching kernel
skips loading the custom drivers; official kernel upgrades remain unrestricted.

The `rpd-battery-m10` service registers standard battery and USB supplies with
voltage, signed current, charging state and temperature. It reads PMI632 QG and
charger registers, including genuine charge termination; it does not change charge current, voltage, limits or safety
protections. Temperature uses the OEM 30 kOhm thermistor curve selected by the
battery ID. An extended copy of the matching upstream ADC driver adds the
missing voltage channel and IIO consumer mappings. The custom ADC has no autoload modalias; its service alone loads it after checks.
Binding is board-specific,
serialized with OTG, refuses unexpected kernel consumers, and restores the
original ADC driver on failure. OTG finds its voltage channel by device path,
not an unstable IIO device index.

Systemd presets enable both services on postmarketOS. No UPower percentage or
kernel CAPACITY is fabricated: the estimated charge/time currently appears in
the Raspberry Pi panel tooltip and `rpd-battery-status` only.

## Estimation and automatic calibration

`rpd-power-monitor` samples every 15 seconds. The initial estimate uses the stock
Lenovo ATL/LWN voltage/SOC curves, temperature and battery ID, starting with the
4850 mAh nominal capacity. Terminal voltage under load is not open-circuit voltage;
this first estimate is approximate and has no validated error bound.

During uninterrupted sampling, current integration tracks charge entering or
leaving the battery. A genuine charger termination indication sustained for five
minutes anchors 100%. Quiet, stable discharge periods can slowly correct drift;
a substantial uninterrupted full-to-rest interval can refine estimated capacity.
No deep discharge is requested. Learning opportunities may be infrequent, and
improvement is not guaranteed just by elapsed usage time. Suspend gaps and
reboots invalidate integration continuity. Gaps up to three minutes preserve the
last estimate without integrating unobserved current; longer gaps reseed SOC
from voltage. Learned capacity and calibration counts are retained.

After three minutes of stable current direction, the monitor estimates runtime
from remaining charge and the recent average consumption. Charging time is an
extrapolation at the recent rate, **not a guaranteed minimum or completion time**:
the final taper, device load and charger changes can alter it substantially.
Insufficient data is shown as calculating, never zero minutes.

State and 30 days of measurement history stay in `/var/lib/rpd-power`; runtime
output is in `/run/rpd-power`. Session notifications warn about low estimated
charge, measured low voltage and elevated temperature. No shutdown or suspend is
triggered from the estimate. Automatic suspend/resume is a separate, unverified
feature and is not enabled by this package.

## Provenance and verification

`m10-profiles.json` records the stock DTB SHA256 and units. Reproduce it with:

```
python3 scripts/extract-m10-battery-profiles.py boot-dtb-1.dtb profiles.json
```

The thermistor conversion follows Lenovo's published `qpnp-adc-common.c`, and
charge/discharge curve semantics follow `qg-battery-profile.c`, revision
`115aa7f0b35f16fda3c7f3b9b08715471849cc25` of the Lenovo kernel reference.

Tests cover units/profile selection, analytic charge integration, gaps/reboots,
real full-charge anchoring, ETA warmup/direction changes, invalid readings,
loader rollback and kernel mismatch. `tests/verify_battery_sysfs.py` compiles the
patched upstream reader against native fixtures for unavailable capacity,
charge/energy fallback, native capacity precedence and stale estimates.

On the M10, live activation has verified real cell temperature near 27.7 C,
positive charging current around 0.4 A, the original panel and active OTG service.
A real reboot verified both services active and enabled before user login, the
custom IIO driver bound, battery readings live, OTG and LightDM active, and no
new kernel BUG/Oops/Call trace in the inspected boot log. Calibration accuracy
requires later observations during real use.
