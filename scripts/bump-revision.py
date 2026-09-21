#!/usr/bin/env python3
"""Give every successful repository rebuild an upgradeable APK revision."""
import json,pathlib,re,subprocess
root=pathlib.Path(__file__).resolve().parents[1]
p=root/'upstream.lock.json';lock=json.loads(p.read_text())
for component in lock.values():component['pkgrel']+=1
p.write_text(json.dumps(lock,indent=2)+'\n')
subprocess.run(['python3',str(root/'scripts/generate.py')],check=True)
for name in ['rpd-session','rpd-desktop-lite','rpd-desktop-m10','rpd-desktop-browser']:
    p=root/'ports'/name/'APKBUILD'
    s,count=re.subn(r'^pkgrel=(\d+)$',lambda m:'pkgrel='+str(int(m[1])+1),p.read_text(),flags=re.M)
    assert count==1
    p.write_text(s)
