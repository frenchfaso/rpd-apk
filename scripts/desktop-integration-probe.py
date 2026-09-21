#!/usr/bin/python3
"""Run in the disposable native desktop home created by headless.sh."""
import json,pathlib,subprocess,tempfile
def run(*args,cwd=None):
    return subprocess.check_output(args,text=True,cwd=cwd,stderr=subprocess.STDOUT)
for mime,app in {'text/plain':'org.xfce.mousepad.desktop','application/pdf':'org.gnome.Evince.desktop','image/png':'eom.desktop','video/mp4':'vlc.desktop','application/zip':'xarchiver.desktop','inode/directory':'pcmanfm.desktop','x-scheme-handler/http':'chromium.desktop','x-scheme-handler/https':'chromium.desktop'}.items():
    result=run('gio','mime',mime)
    assert app in result and 'No default applications' not in result,(mime,result)
run('rpd-user-settings','browser','chromium')
assert run('rpd-user-settings','get-browser').strip()=='chromium.desktop'
with tempfile.TemporaryDirectory() as temp:
    p=pathlib.Path(temp);(p/'test.txt').write_text('RPD archive round trip\n')
    run('zip','-q','test.zip','test.txt',cwd=temp)
    assert run('unzip','-p','test.zip','test.txt',cwd=temp)=='RPD archive round trip\n'
    run('7z','a','test.7z','test.txt',cwd=temp)
    assert run('7z','x','-so','test.7z','test.txt',cwd=temp)=='RPD archive round trip\n'
prefs=json.loads(pathlib.Path('/usr/lib/chromium/initial_preferences').read_text())
assert prefs['extensions']['theme']['use_system']
assert 'initial_extensions' not in prefs
policy=json.loads(pathlib.Path('/etc/chromium/policies/recommended/rpd.json').read_text())
assert policy['DefaultSearchProviderName']=='DuckDuckGo'
assert pathlib.Path(prefs['distribution']['import_bookmarks_from_file']).is_file()
print('GIO associations, Chromium defaults and ZIP/7z round trips passed')
