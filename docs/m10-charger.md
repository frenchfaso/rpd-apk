# Lenovo M10 charge termination

`rpd-desktop-m10` includes `rpd-charger-m10`. Its system service configures only
the PMI632 upper ADC charge-termination threshold, using **-170 mA** from the
stock M10 device tree and the [pinned Lenovo driver conversion](https://github.com/Lenovo-TB-X505X/android_kernel_lenovo_TB-X505X/blob/115aa7f0b35f16fda3c7f3b9b08715471849cc25/drivers/power/supply/qcom/qpnp-smb5.c).
The exact big-endian bytes are `fb a6`, written only to `0x1067–0x1068`.

This is an interim, board-specific correction, not a complete replacement for
the Android charger/BMS driver. Voltage/current limits, thermal protection,
JEITA compensation, lower termination threshold and recharge policy remain
unchanged. The gauge and userspace estimator remain read-only with respect to
charger configuration.

## Operation

The oneshot service starts after M10 battery telemetry. Before writing, it
checks the Lenovo board, exact kernel/package match, PMI632 identity, ATL
battery ID, valid temperature/voltage, inactive OTG, fault flags and known charger
configuration. Unknown upper thresholds are refused; an already correct value
is accepted without writing or taking ownership. A native PMIC power-supply
provider causes the service to skip this integration.

Configuration happens before charge completion, including when running from
battery. This follows the OEM initialization model: the hardware comparator
must already be configured when charging completes during s2idle. Normal
operation has **no polling, held wake lock or sleep inhibitor**.

Stopping the service verifies restoration before unloading. An active change
pins only this small module, **not the kernel APK**. Failed or partial writes
are rolled back; failed rollback keeps the module available for retries.
A different owner's value is preserved, with an explicit ownership warning.
Service ordering stops the correction before its battery-telemetry dependency.

An unsupported kernel is skipped rather than blocking an official kernel
upgrade. The repository's existing authenticated kernel update/build process
also builds this module; the loader still requires the exact installed/running
kernel match. No generic DKMS-style compatibility promise is implied.

## Validation and limits

On the tested TB-X505L with ATL battery and `7.1.3-msm89x7`, replacing the inherited
`7b a4` value caused hardware TERMINATE within five seconds. During the isolated
eight-minute trial, current remained zero, temperature 25.1–25.2 C, and only the
threshold and charging-state registers changed. Exact rollback also passed.
The unmodified estimator accepted its first full-charge reference after five
minutes; this is an SOC anchor, not a measurement of effective capacity.

Tests cover the byte transaction, signed encoding, changed baseline, partial
write/read errors, masked sign, rollback retries, idempotent configuration,
ownership conflicts and loader exclusion/cleanup paths. Clean-root packaging
tests require the module, loader and enabled-service preset in the metapackage.

Full charge/discharge/recharge and overnight s2idle validation of the permanent
integration remain separate device tests. Initial configuration is deliberately
restricted to 20–35 C and the observed ATL hardware setup. Conditions outside
the startup guards are reported as a service failure and retried once a minute;
none of the existing hardware protection settings is relaxed.

Useful diagnostics:

```sh
systemctl status rpd-charger-m10
sudo cat /sys/module/m10_charger/parameters/status
cat /sys/class/power_supply/m10-battery/status
```
