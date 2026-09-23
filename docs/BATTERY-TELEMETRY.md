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
4850 mAh nominal capacity. A new voltage seed waits three minutes, discards the
first minute and takes the median of the subsequent readings. This reduces boot
load/transient sensitivity; **it does not turn loaded voltage into open-circuit
voltage or provide a validated accuracy bound**.

During uninterrupted sampling, current integration tracks charge entering or
leaving the battery. On the M10 it now prefers the PMI632 QG FIFO and partial
accumulator: the current configuration measures every 300 ms, averages 256
samples per FIFO entry and retains eight entries (614.4 seconds). Successive
snapshots count only newly measured samples, including across FIFO wrap and
charge/discharge transitions. Both charge integration and the smoothed rate used
for ETAs use this interval measurement. Missing, inconsistent or mismatched
windows fall back explicitly to the periodic instantaneous samples.

The driver exposes a root-only, read-only `qg_snapshot`. It checks FIFO and
accumulator counters before and after reading; moving snapshots are retried.
The decoder checks configuration, cadence and coverage. It never holds, resets
or clears the gauge and never counts a repeated window twice. This is continuous
hardware sampling with software integration of its bounded window, not a
persistent lifetime charge counter. Sampling gaps/reboots still invalidate
capacity-learning intervals.

Changed hardware power-on voltage/current may supply a better initial reference
only early in a new boot, when a brief resume cannot preserve the prior estimate.
A newly observed hardware rest reference must remain unchanged on the next poll
before it is accepted. Untimestamped references already present at service
startup are not reused as fresh measurements. Both paths require plausible
low-current readings and temperature; acceptance is reported separately from
capacity learning. The captured power-on sample was about 3.825 V at 19 mA load,
but was not applied retroactively to the running tablet. The hardware rest
reference is still unavailable in the live traces. The current hardware sleep
entry threshold is about 10 mA, far below the active Linux desktop load; reading
more registers alone does not establish a relaxed-voltage reference.

 Genuine charger termination sustained for five minutes
anchors 100%. Quiet discharge periods (at most 80 mA for ten minutes, within
5 mV of their starting voltage and 2 C, at 10..45 C) permit approximate voltage
references. These heuristic gates are not proof of electrochemical relaxation.

Capacity learning accepts full-to-rest or partial rest-to-rest discharge intervals:
at least 35 percentage points and 1000 mAh, endpoint temperatures within 3 C,
and partial-reference currents within 20 mA. Two independent capacity candidates
must agree within 10%; only then does the model apply a 10% correction. Reboots,
sampling gaps and substantial charging invalidate the integration interval.
Implausible capacities outside 50..110% of nominal are rejected. No deep discharge
is requested. The thresholds are conservative heuristics, not a validated fuel
gauge algorithm. **Partial cycles can provide references, but arbitrary daily
use does not guarantee calibration or monotonically improving accuracy.**
The first retained M10 traces never reached the low-current reference condition;
capacity remained nominal with zero updates. Counters report actual accepted
candidates/updates, rather than assuming that collecting samples is learning.

Gaps up to three minutes preserve the last estimate without integrating
unobserved current; longer gaps start a new filtered seed. Learned capacity and
calibration counts persist. An exhausted estimate (which would round to zero)
is marked unavailable, including both ETAs, until a new reference is available.
Simply reconnecting the charger cannot recover an unknown starting SOC.
The schema-compatible upgrade replaces an already exhausted legacy seed once
with the new delayed seed, retaining capacity and measurement history. This
reinitialization is not a capacity calibration.

After three minutes of consistent current direction, runtime uses remaining
estimated charge and recent average consumption. Charging time extrapolates the
recent rate: taper, device load and charger changes can alter it substantially.
The panel shows "Percentage unavailable" while collecting a seed or after an
exhausted reference; `rpd-battery-status` also explains the estimation and learning
state. Otherwise both charge and time remain explicitly provisional estimates.

### Laptop reference architecture

System76's public [EC battery reader](https://github.com/system76/ec/blob/master/src/app/main/battery.c)
reads percentage, remaining/full capacity and cycle count over SMBus from the
battery. It does not derive these values from terminal voltage in the desktop.
[Apple documents](https://support.apple.com/en-ca/102589) maximum-capacity
recalibration and temperature/charging-history management, but not a complete
portable implementation of its estimation algorithm.

The appropriate M10 analogue is fuller support for the PMI632 QG measurement and
Lenovo/Qualcomm estimation path, including validated references and continuity.
The OEM kernel exchanges SOC values with userspace; copying its driver alone is
insufficient. We use its documented QG scaling, FIFO and accumulator semantics,
but do not substitute stale SOC/SDAM bytes for valid capacity. OEM-disabled ESR
excitation remains disabled; undocumented impedance tables are not guessed. Native kernel capacity,
when available, already takes precedence in our panel. Charger control and
battery health/charge-limit policies are separate from this userspace estimate.

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

Tests cover units/profile selection, analytic charge integration, filtered startup,
gaps/reboots, exhausted estimates, migration, partial-reference gates, real full
recovery, ETA warmup/direction changes, invalid readings,
hardware signed units, interval integration, FIFO wrap, variable loads, repeated
windows, cadence/configuration changes and stale/fresh hardware references,
loader rollback and kernel mismatch. `tests/verify_battery_sysfs.py` compiles the
patched upstream reader against native fixtures for unavailable capacity,
charge/energy fallback, native capacity precedence and stale estimates.

On the M10, live activation has verified real cell temperature near 27.7 C,
positive charging current around 0.4 A, the original panel and active OTG service.
A real reboot verified both services active and enabled before user login, the
custom IIO driver bound, battery readings live, OTG and LightDM active, and no
new kernel BUG/Oops/Call trace in the inspected boot log. Calibration accuracy
requires later observations during real use.

The hardware integration revision was tested on the M10 without reboot: 24 of
24 intervals in a 120-second discharge trace had valid hardware coverage
(total 10.038 mAh). A subsequent live charger transition and FIFO index 7-to-0
wrap retained hardware integration without a percentage jump. Native tests also
compile the actual C snapshot reader and exercise moving counters, bus errors
and missing regmap; host sanitizer checks pass. The read-only module was built
against the running kernel and its imports audited for register writes.
Hardware OCV acceptance and learned-capacity accuracy still require real-device
validation; unit tests alone do not validate electrochemical estimates.
