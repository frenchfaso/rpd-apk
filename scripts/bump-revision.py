#!/usr/bin/env python3
"""Give every successful repository rebuild an upgradeable APK revision."""
import json,pathlib,re,subprocess
root=pathlib.Path(__file__).resolve().parents[1]
p=root/'upstream.lock.json';lock=json.loads(p.read_text())
for component in lock.values():component['pkgrel']+=1
p.write_text(json.dumps(lock,indent=2)+'\n')
subprocess.run(['python3',str(root/'scripts/generate.py')],check=True)
for name in ['rpd-power','squeekboard','rpd-cpu-topology-m10','rpd-backlight-m10','rpd-autorotate','rpd-settings-backend','labwc','gtk-layer-shell','rpd-login','rpd-session','rpd-desktop-lite','rpd-desktop-m10','rpd-desktop-browser']:
    p=root/'ports'/name/'APKBUILD'
    s,count=re.subn(r'^pkgrel=(\d+)$',lambda m:'pkgrel='+str(int(m[1])+1),p.read_text(),flags=re.M)
    assert count==1
    p.write_text(s)

# Keep the tested gesture compositor pinned on the M10 until its next review.
labwc=(root/'ports/labwc/APKBUILD').read_text()
version=re.search(r'^pkgver=(.+)$',labwc,re.M)[1]
revision=re.search(r'^pkgrel=(.+)$',labwc,re.M)[1]
p=root/'ports/rpd-desktop-m10/APKBUILD'
p.write_text(re.sub(r'labwc=[^" ]+', 'labwc='+version+'-r'+revision,p.read_text()))
