# Lenovo M10 internal speakers

`rpd-desktop-m10` includes `rpd-audio-m10`. Its HiFi profile exposes **Internal
Speakers** to PipeWire and the standard Raspberry Pi volume panel. Bluetooth
audio keeps using the existing stack. Wired headphones and microphones are not
enabled by this profile.

The PM8953 codec feeds two external amplifiers through HPHL/HPHR. Their enable
pins use the two-pulse sequence found in the matching Lenovo Android driver.
The amplifier part number is not known. ALSA DAPM powers them only while needed.
Codec gain is limited to -12 dB; PipeWire controls both channels in software.

## Kernel integration

Three optional modules are compiled alongside the existing M10 modules against
the authenticated official kernel configuration and complete export metadata:

- PM8953 secondary SPMI address support, restricted to this board and USID 1;
- the PM8953 analog codec, including Cajon 2 initialization;
- the board's speaker amplifier enable protocol.

The boot-deploy hook runs after the CPU topology hook. It selects the audio DTB
only if the installed kernel APK, the three modules and the contents of the
current official DTB match the build. It always starts from the current kernel's
DTB, preserving the four-core correction. On a mismatch or error, audio is
disabled and the new official kernel still boots. No kernel package is pinned.
GitHub's existing kernel tracker rebuilds this subpackage with the other modules.

Removing the package regenerates boot files without the audio hook. A reboot is
required when enabling or disabling the hardware description.

## Sources

- [PM8953 codec reference](https://github.com/msm8953-mainline/linux/blob/7213855948c70fd165356526f1de1c3b6bf4d554/sound/soc/codecs/msm8916-wcd-analog.c).
- SPMI glue derives from the exact kernel's `drivers/mfd/qcom-spmi-pmic.c` and
  applies the packaged patch, retaining the original driver for other addresses.
- Board audio extends the matching official TB-X505X source and shared
  `msm8937-qdsp6.dtsi`; it does not replace the kernel or unrelated board support.
- Amplifier DAPM structure follows Linux `sound/soc/codecs/aw8738.c`; compatibility
  is board-specific because the physical amplifier has not been identified.

Build checks cover symbol resolution, unrelated DT properties, missing modules,
kernel updates and changed official trees. On-device verification additionally
checks real playback, the desktop profile and restart behavior.
