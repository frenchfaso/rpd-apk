#!/bin/sh
# Complete-kernel candidate only; disposable native ARM, no production key.
set -eu
[ "$(uname -m)" = aarch64 ] && [ "$(id -u)" = 0 ]
[ -f /etc/alpine-release ]
[ -f /.dockerenv ] || [ -f /run/.containerenv ]
[ -d /out ]
[ -n "${RPD_SOURCE_COMMIT:-}" ]
[ "${ABUILD_LAST_COMMIT:-}" = "$RPD_SOURCE_COMMIT" ]
case "${SOURCE_DATE_EPOCH:-}" in ''|*[!0-9]*) exit 2;; esac
cd "$(dirname "$0")/.."
export RPD_DISPOSABLE_BUILD=1
export ABUILD_USERDIR=/home/builder/.abuild REPODEST=/home/builder/packages
out=/out
work=/home/builder/rpd-kernel-security
mkdir -p "$out/metrics" "$out/proof" "$out/sources" "$out/aarch64" "$out/keys"
date -u +%FT%TZ > "$out/started.txt"
apk add --no-cache alpine-sdk python3 sudo curl time util-linux
python3 scripts/update-m10-kernel.py --validate-local > "$out/proof/kernel-provider-validation.json"
install -m644 keys/build.postmarketos.org.rsa.pub /etc/apk/keys/
printf '\n@pmos https://mirror.postmarketos.org/postmarketos/main\n' >> /etc/apk/repositories
# Keep its world entry untagged so the official-only toolchain helper can retain
# the installed build tool while deliberately hiding non-Alpine repositories.
apk add --no-cache --repository https://mirror.postmarketos.org/postmarketos/main postmarketos-installkernel
{
    uname -a
    lscpu
    free -m
    df -h
} > "$out/metrics/environment.txt"

adduser -D builder
addgroup builder abuild
printf 'builder ALL=(ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/rpd-builder
mkdir -p "$ABUILD_USERDIR" "$REPODEST" "$work"
cp -a ports scripts toolchains keys "$work/"
install -m644 scripts/source-download.curlrc /home/builder/.curlrc
mkdir -p /usr/lib/modules
[ -e /lib/modules ] || ln -s /usr/lib/modules /lib/modules
chown -R builder:builder /home/builder
su builder -c 'abuild-keygen -a -i -n'
cp "$ABUILD_USERDIR"/*.pub /etc/apk/keys/

# Resolve the panel plugin before either expensive build. Only this clean root
# trusts the published RPD repository; it never enters the compiler environment.
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
mkdir -p "$root/etc/apk/keys"
cp /etc/apk/keys/*.pub "$root/etc/apk/keys/"
install -m644 keys/rpd-apk.rsa.pub "$root/etc/apk/keys/"
cp /etc/apk/repositories "$root/etc/apk/repositories"
printf '\n@published https://frenchfaso.github.io/rpd-apk\n' >> "$root/etc/apk/repositories"
apk --root "$root" --initdb --no-scripts add 'rpd-battery@published>=1.11-r23'
apk --root "$root" info --installed -v > "$out/proof/runtime-dependency-preflight.txt"
sha256sum keys/rpd-apk.rsa.pub > "$out/proof/published-repository-key.sha256"
printf '\n%s/ports\n' "$REPODEST" >> /etc/apk/repositories

# Build the reviewed canonical recipes; no candidate-only recipe rewriting.
python3 - "$work" <<'PY'
import hashlib, json
from pathlib import Path
import re, sys
root = Path(sys.argv[1])
module = root / 'ports/rpd-backlight-m10'
kernel = root / 'ports/linux-postmarketos-qcom-msm89x7'
assert (module/'kernel.config').read_bytes() == (kernel/'config-postmarketos-qcom-msm89x7.aarch64').read_bytes()
assert (module/'check-kernel-config.py').read_bytes() == (kernel/'check-kernel-config.py').read_bytes()
metadata = json.loads((kernel/'security-fixes.json').read_text())
assert metadata['kernel_apk_version'] == '7.1.3-r100'
assert metadata['kernel_release'] == '7.1.3-msm89x7'
assert [fix['cve'] for fix in metadata['fixes']] == [
    'CVE-2026-98858', 'CVE-2026-98823', 'CVE-2026-72112', 'CVE-2026-98850',
    'CVE-2026-100077', 'CVE-2026-93059', 'CVE-2026-81000', 'CVE-2026-98829']
recipe = (module/'APKBUILD').read_text()
assert re.search(r'^pkgver=7\.1\.3$', recipe, re.M)
revision = re.search(r'^pkgrel=(\d+)$', recipe, re.M)
assert revision is not None and int(revision[1]) >= 100
assert re.search(r'^_kernel_apk_version=7\.1\.3-r100$', recipe, re.M)
assert re.search(r'^expected_apk=7\.1\.3-r100$', (module/'rpd-backlight-m10-load').read_text(), re.M)
for fix in metadata['fixes']:
    name = fix['patch']
    assert re.fullmatch(r'000[1-8]-CVE-2026-[0-9]+\.patch', name)
    data = (kernel/name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == fix['sha256']
    assert (module/name).read_bytes() == data
    for port in (module,kernel):
        text = (port/'APKBUILD').read_text()
        source = re.search(r'^source="(.*?)"\n',text,re.M|re.S)
        assert source is not None and source[1].split().count(name) == 1
        assert re.findall(r'^([0-9a-f]{128})  '+re.escape(name)+r'$',text,re.M) == [hashlib.sha512(data).hexdigest()]
PY
chown -R builder:builder "$work"
cp "$work/ports/rpd-backlight-m10/APKBUILD" "$out/proof/rpd-backlight-m10.APKBUILD"
cp "$work/ports/rpd-backlight-m10/rpd-backlight-m10-load" "$out/proof/rpd-backlight-m10-load"
cp "$work/ports/linux-postmarketos-qcom-msm89x7/APKBUILD" "$out/proof/kernel.APKBUILD"
cp "$work/ports/linux-postmarketos-qcom-msm89x7/security-fixes.json" "$out/proof/"

build() {
    /usr/bin/time -v -o "$out/metrics/$1.txt" \
        su builder -c "cd $work/ports/$1 && abuild -r"
    apk update
}

build rpd-cpu-topology-m10
apk add --no-cache rpd-cpu-topology-m10
python3 "$work/scripts/m10-toolchain.py" install
{
    /usr/lib/llvm23/bin/clang --version
    /usr/bin/ld.lld --version
    apk info --installed -v clang23 clang23-libs lld23 llvm23 llvm23-libs
} > "$out/proof/toolchain.txt"
build linux-postmarketos-qcom-msm89x7

# Both recipes declare the same authenticated archive under different aliases.
# Verify bytes before sharing a cache inode, avoiding another 250 MiB download.
python3 - "$work" <<'PY'
import hashlib, json, os
from pathlib import Path
import sys
root = Path(sys.argv[1])
data = json.loads((root/'ports/linux-postmarketos-qcom-msm89x7/security-fixes.json').read_text())
original = Path('/var/cache/distfiles/linux-postmarketos-qcom-msm89x7-v7.1.3-r1.tar.gz')
alias = Path('/var/cache/distfiles/linux-v7.1.3-r1.tar.gz')
def digest(path):
    h=hashlib.sha512()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
assert digest(original) == data['base_board_archive_sha512']
if alias.exists():
    assert digest(alias) == data['base_board_archive_sha512']
else:
    os.link(original,alias)
PY
build rpd-backlight-m10

kernel="$work/ports/linux-postmarketos-qcom-msm89x7/src/linux-7.1.3-r1"
module="$work/ports/rpd-backlight-m10/src/linux-7.1.3-r1"
# A successful compile alone is insufficient: require identical generated config
# and real built-in export metadata from both full preparations.
cmp "$kernel/.config" "$module/.config"
cmp "$kernel/vmlinux.symvers" "$module/vmlinux.symvers"
cp "$kernel/.config" "$out/proof/kernel.config"
cp "$kernel/Module.symvers" "$out/proof/kernel.Module.symvers"
cp "$kernel/vmlinux.symvers" "$out/proof/kernel.vmlinux.symvers"
cp "$module/.config" "$out/proof/module.config"
cp "$module/Module.symvers" "$out/proof/module.Module.symvers"
cp "$module/vmlinux.symvers" "$out/proof/module.vmlinux.symvers"
cp "$kernel/include/config/kernel.release" "$out/proof/kernel.release"
cp "$kernel/include/generated/utsversion.h" "$out/proof/kernel.utsversion.h"
for fix in 0001-CVE-2026-98858.patch 0002-CVE-2026-98823.patch \
           0003-CVE-2026-72112.patch 0004-CVE-2026-98850.patch \
           0005-CVE-2026-100077.patch 0006-CVE-2026-93059.patch \
           0007-CVE-2026-81000.patch 0008-CVE-2026-98829.patch; do
    patch --batch --reverse --fuzz=0 --dry-run -d "$module" -p1 \
        < "$work/ports/rpd-backlight-m10/$fix"
done
python3 "$work/scripts/m10-toolchain.py" restore

cp "$REPODEST"/ports/aarch64/*.apk "$out/aarch64/"
cp "$REPODEST"/ports/aarch64/APKINDEX.tar.gz "$out/aarch64/"
cp "$ABUILD_USERDIR"/*.pub "$out/keys/"
cp /var/cache/distfiles/linux-postmarketos-qcom-msm89x7-v7.1.3-r1.tar.gz "$out/sources/"
for apkfile in "$out"/aarch64/*.apk; do apk verify "$apkfile"; done
python3 - "$out" <<'PY'
import gzip,json,os,re,tarfile
from pathlib import Path
import sys
out=Path(sys.argv[1])
expected=os.environ['RPD_SOURCE_COMMIT']
assert re.fullmatch(r'[0-9a-f]{40}',expected)
packages={}
for package in sorted((out/'aarch64').glob('*.apk')):
    with gzip.open(package,'rb') as stream:
        with tarfile.open(fileobj=stream,mode='r|',ignore_zeros=True) as archive:
            for member in archive:
                if member.name.removeprefix('./') == '.PKGINFO':
                    info=archive.extractfile(member).read().decode()
                    break
            else:raise ValueError('Missing APK control metadata: '+package.name)
    commits=re.findall(r'^commit = (.*)$',info,re.M)
    assert commits == [expected],(package.name,commits,expected)
    packages[package.name]=expected
(out/'proof/apk-source-commits.json').write_text(json.dumps(packages,indent=2)+'\n')
PY

# Every candidate is explicitly selected from the authenticated local files,
# including equal-version module packages also present in the published repo.
apk --root "$root" --no-scripts add "$out"/aarch64/*.apk
apk --root "$root" info -e linux-postmarketos-qcom-msm89x7=7.1.3-r100
apk --root "$root" info --installed -v > "$out/proof/installed-packages.txt"
cmp "$root/boot/config" "$kernel/.config"
cmp "$root/boot/vmlinuz" "$kernel/arch/arm64/boot/vmlinuz"
cmp "$root/boot/dtbs/qcom/sdm429-lenovo-tbx505x.dtb" \
    "$kernel/arch/arm64/boot/dts/qcom/sdm429-lenovo-tbx505x.dtb"
grep -qx 'expected_apk=7.1.3-r100' "$root/usr/libexec/rpd-backlight-m10-load"
python3 - "$root" "$out" <<'PY'
import hashlib,json,os
from pathlib import Path
import sys
root,out=map(Path,sys.argv[1:])
names=['rpd-gpu-m10','rpd-usb-otg-m10','rpd-battery-m10','rpd-charger-m10','rpd-audio-m10']
metadata={name:json.loads((root/'usr/lib'/name/'kernel.json').read_text()) for name in names}
fixes=json.loads((out/'proof/security-fixes.json').read_text())['fixes']
for name,item in metadata.items():
    assert item == {'release':'7.1.3-msm89x7','apk':'7.1.3-r100'}, (name,item)
config=(out/'proof/kernel.config').read_text()
assert 'CONFIG_CFI=y\n' in config and '# CONFIG_CFI_PERMISSIVE is not set\n' in config
assert 'CONFIG_DEBUG_INFO_BTF=y\n' in config
receipt={'source_commit':os.environ.get('RPD_SOURCE_COMMIT'),
 'abuild_commit':os.environ['ABUILD_LAST_COMMIT'],
 'source_date_epoch':int(os.environ['SOURCE_DATE_EPOCH']),
 'kernel':'linux-postmarketos-qcom-msm89x7=7.1.3-r100','kernelrelease':'7.1.3-msm89x7',
 'full_kernel_built':True,'matching_rpd_modules_built':True,
 'generated_config_and_builtin_exports_identical':True,
 'apk_signatures':'verified with ephemeral build key','clean_root_install_no_scripts':'passed',
 'runtime_dependency_provider':'signed published RPD repository, tagged and preflighted before builds',
 'candidate_selection':'explicit authenticated local APK paths; published compiler inputs excluded',
 'hardware_qualification':'not performed','production_publication':False,
 'module_metadata':metadata,
 'security_fixes':[fix['cve'] for fix in fixes],
 'conditional_applicability':[fix['cve'] for fix in fixes if 'applicability' in fix],
 'proof_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'proof').iterdir() if p.is_file()}}
(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
PY
date -u +%FT%TZ > "$out/finished.txt"
printf '%s\n' 'Complete security kernel, exact matching modules, signatures and clean-root install passed.' \
    'Candidate only: Linux 7.1 remains EOL; no production publication or hardware qualification.' > "$out/validation.txt"
