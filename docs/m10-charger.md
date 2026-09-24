# Lenovo M10 charger corrections

`rpd-desktop-m10` includes `rpd-charger-m10`. Its system service configures the PMI632 upper ADC charge-termination threshold,
using **-170 mA** from the
stock M10 device tree and the [pinned Lenovo driver conversion](https://github.com/Lenovo-TB-X505X/android_kernel_lenovo_TB-X505X/blob/115aa7f0b35f16fda3c7f3b9b08715471849cc25/drivers/power/supply/qcom/qpnp-smb5.c).
The exact big-endian bytes are `fb a6`, written to `0x1067–0x1068`.
It also sets the ATL battery's **soft-hot threshold** to `0f b3` at
`0x1094–0x1095`, using the stock battery profile and `smblib_update_jeita`.
These two two-byte registers are the only write targets.

This is an interim, board-specific correction, not a complete replacement for
the Android charger/BMS driver. Voltage/current limits, hard-hot/hard-cold shutdown thresholds, soft-cold,
JEITA enable/compensation settings, lower termination threshold and recharge
policy remain unchanged. Only the erroneous soft-hot boundary is corrected;
this is not a complete port of the Android thermal profile. The gauge and userspace estimator remain read-only with respect to
charger configuration.

## Operation

The service starts after M10 battery telemetry and enables a small kernel
listener for the existing `m10-usb` power-supply notifications. Before writing, it
checks the Lenovo board, exact kernel/package match, PMI632 identity, ATL
battery ID, valid temperature/voltage, inactive OTG, fault flags and known charger
configuration. Unknown values of either threshold are refused; an already correct value
is accepted without writing or taking ownership. A native PMIC power-supply
provider causes the service to skip this integration.

On this unit a write without USB input was ignored; readback detected the
mismatch and rollback passed. The integration therefore waits without writing
while USB is absent, and applies the threshold on an existing supply notification
once USB and the guard conditions are valid. It also checks immediately before
suspend and after resume, covering a Power press soon after connecting a charger.
No dedicated polling timer or sleep inhibitor is used in normal operation.

Repeated notifications only verify both configured values. If the hardware restores
either known default after an input-power cycle, the next qualified USB event
reapplies the correction. Unknown values are preserved and disable further
writes while restoring any other setting still owned by this module. A write/readback failure is latched until service restart; the original
bytes of both owned settings are restored in reverse order, with retries only
if that rollback fails. A partial reset of one register retains ownership of
the other until its original value is restored.

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

A separate two-minute soft-hot trial resolved a connected-but-discharging
condition at 25.4 C: changing only `1b ff` to `0f b3` cleared the Warm flag and
changed net battery current from negative to positive. Restoring `1b ff`
restored the Warm flag and discharge. Hard thermal limits and charge limits
were untouched. This qualifies the ambient-temperature correction, not all
thermal conditions or the inherited hard thresholds.

Tests cover the byte transaction, signed encoding, changed baseline, partial
write/read errors, masked sign, rollback retries, idempotent configuration,
ownership conflicts and loader exclusion/cleanup paths. Clean-root packaging
tests require the module, loader and enabled-service preset in the metapackage.

Full charge/discharge/recharge and overnight s2idle validation of the permanent
integration remain separate device tests. Configuration is deliberately
restricted to 20–35 C and the observed ATL hardware setup. Conditions outside
the guards defer application until the next existing supply notification. A
service-level failure is retried once a minute. Plugging in while the tablet is
already asleep is not yet qualified; configure while awake before a long
s2idle charging test. Hardware thermal shutdown remains enabled with its inherited thresholds. Those
thresholds are still different from the stock ATL profile: this correction
resolves false Warm at room temperature, not full-range thermal qualification.

Useful diagnostics:

```sh
systemctl status rpd-charger-m10
sudo cat /sys/module/m10_charger/parameters/status
cat /sys/class/power_supply/m10-battery/status
```
