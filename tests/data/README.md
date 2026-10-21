# M10 kernel build-rule fixtures

`m10-Kbuild.include` and `m10-Makefile.btf` are unchanged upstream files from
`msm89x7-mainline/linux`, tag `v7.1.3-r1`, paths `scripts/Kbuild.include` and
`scripts/Makefile.btf`. They retain their upstream GPL-2.0 SPDX notices; the
corresponding upstream license is in `GPL-2.0`.

Tests execute these real rules to check the pahole metadata exception, including
rejection of changed encoding/module-resolver flags and kernel configuration.
Production always evaluates the files from the authenticated kernel source being
built, rather than these fixtures.

SHA256:

```
1953e3cb531ea8d93dfd0de7779e89dd4243f550e070d99356887e0121a70de9  m10-Kbuild.include
27edbcabe5ada34f6fcc13b8b10948024191508da283c357ea54d07922588b0e  m10-Makefile.btf
```
