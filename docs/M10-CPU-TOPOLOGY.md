# M10 CPU topology correction

The Lenovo TB-X505L has Snapdragon 429 and four Cortex-A53 CPUs. The current
7.1.3-msm89x7 DTB inherits eight CPU nodes from SDM439/MSM8937: MPIDRs 0-3 are
unavailable, while 0x100-0x103 are the physical CPUs. Firmware rejects the former,
leaving Linux IDs 0,5,6,7 online and four offline slots.

`rpd-cpu-topology-m10` derives a corrected DTB from the currently installed
`/boot/dtbs/qcom/sdm429-lenovo-tbx505x.dtb`. The official file and kernel binary
remain untouched. The derived copy lives at
`/boot/dtbs/rpd/sdm429-lenovo-tbx505x.dtb`; the package's `/etc/deviceinfo` override
selects it, and normal boot-deploy copies it to the active boot directory.

The standard `/usr/share/boot-deploy/hooks` integration regenerates this copy
before each kernel deployment, including the mkinitfs trigger on `apk upgrade`.
A `/usr/share/mkinitfs-triggers` marker also deploys it on initial installation.
There is no kernel-version dependency, pinned kernel, custom kernel build,
boot-time hotplug or module. Existing `/etc/deviceinfo` customizations must be
merged with the packaged override if APK preserves that file as a user config.

The helper validates board compatibility, MPIDRs, CPU-map phandles and remaining
CPU/cache/cooling references before removing the unavailable cluster. It renames
the retained topology cluster to cluster0 so Linux sees contiguous cluster
numbering, while preserving the real CPU addresses, phandles, clocks, thermal
maps and every unrelated node/property. libfdt performs the edits atomically on
a derived file. An already fixed four-CPU DTB is passed through unchanged.

If a future kernel changes the structure unexpectedly, the generated copy is
replaced with that kernel's unmodified official DTB. Thus an unsupported change
can restore the cosmetic offline slots, but does not pin the old kernel or reuse
an old DTB. A missing source at the known path leaves normal distribution DTB
selection in effect. Ordinary I/O/disk failures remain boot-deploy errors.

Removing the package removes its deviceinfo override and runs mkinitfs to restore
distribution selection. The unused derived copy can be deleted afterward.
To restore manually, remove only this package's DTB selection from
`/etc/deviceinfo`, then run `sudo mkinitfs` before rebooting.

Validation: eight tests cover the four-CPU map, idempotence, upstream fixes,
unrelated kernel changes, incompatible boards/topology/references, and replacing
a stale derived DTB with the current official input. The real M10 DTB is also
compared property-for-property; dtc reports no additional warnings after editing.
Hardware boot verification is recorded in the FP2 project device notes.

## Verified on the device, 2026-09-22

After installing 0.1.0-r1 through APK, the normal mkinitfs trigger ran the hook and
selected the generated DTB. Kernel and official DTB SHA256 stayed unchanged.
After the authorized reboot on 7.1.3-msm89x7:

- possible/present/online: `0-3`; offline: empty.
- Boot log: four processors activated, no failed CPU boot messages.
- cpufreq policy0 covers CPUs 0 1 2 3, with the original 960 MHz–2.016 GHz OPPs.
- LightDM, NetworkManager, Bluetooth and the USB OTG service active;
  greeter autorotation running and `m10_backlight` present.

Official DTB SHA256:
`f1e33bf16e6a35e945ff2bf205817f014208f94598d93600d4c27df8b5ef0637`

Active derived DTB SHA256:
`b9b590f069410a27666b85ea2202ba5f15897567977835b9e25da7aaf701e546`
