# Lenovo M10 passive USB OTG

`rpd-usb-otg-m10` is included in `rpd-desktop-m10` and built alongside the
backlight modules against the same verified official kernel. It does not depend
on a particular kernel package version, so official kernel upgrades are never
held back. Startup skips activation if the running release or installed kernel
APK revision differs; a later repository build provides matching modules.

On the verified TB-X505L, the service detects a passive micro-USB OTG adapter and
switches ChipIdea to host mode with a 500mA VBUS limit. Removing it restores gadget
mode and disables the source. Raspberry Pi USB keyboard (integrated Genesys hub)
and PixArt mouse were verified together, including automatic attachment/removal.
Powered Y cables, simultaneous charging and pogo docks are not supported.

The circuit needs more than the PMI632 VBUS regulator: Lenovo's GPIO94 enables
the USB power path, GPIO130 isolates the pogo path, GPIO124 detects ID, L16 powers
its pull-up at1.8V, and PMI632 GPIO1 must be high-impedance for analog ID sensing.
Reference: Lenovo kernel commit
`115aa7f0b35f16fda3c7f3b9b08715471849cc25`, `drivers/usb/phy/phy-msm-usb.c`,
`drivers/power/supply/qcom/smb5-lib.c`, and stock SDM429/PMI632 device tree.

The modules use regulator, GPIO and pinctrl APIs, restore the verified initial
pin configuration on removal, and do not program charging or boost voltages.
The supervisor refuses initial activation if external VBUS is already present.
It is supervised by systemd, with an additional ExecStopPost cleanup path.

The APK enables the service for `lenovo,tbx505x`. Start it after installation:

```
sudo systemctl start rpd-usb-otg-m10
systemctl status rpd-usb-otg-m10
```

Disable and restore the normal USB role with:

```
sudo systemctl disable --now rpd-usb-otg-m10
```

Current integration is systemd-only. Kernel ABI mismatch, missing resources, or
sensor read failure leaves OTG unavailable rather than overriding the guards.
