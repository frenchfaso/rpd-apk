#!/usr/bin/python3
"""Run in the disposable native desktop home created by headless.sh."""
import json,os,pathlib,shutil,subprocess,tempfile
def run(*args,cwd=None,env=None):
    return subprocess.check_output(args,text=True,cwd=cwd,env=env,stderr=subprocess.STDOUT)
for mime,app in {'text/plain':'org.xfce.mousepad.desktop','application/pdf':'org.gnome.Evince.desktop','image/png':'eom.desktop','video/mp4':'vlc.desktop','application/zip':'xarchiver.desktop','inode/directory':'pcmanfm.desktop'}.items():
    result=run('gio','mime',mime)
    assert app in result and 'No default applications' not in result,(mime,result)
assert shutil.which('epiphany'), 'GNOME Web is required'
browsers={'epiphany':'org.gnome.Epiphany.desktop','chromium':'chromium.desktop','firefox':'firefox.desktop'}
browser_mimes=['text/html','application/xhtml+xml','x-scheme-handler/http','x-scheme-handler/https']
# Exercise defaults and choices in fresh XDG directories without changing user preferences.
with tempfile.TemporaryDirectory() as temp:
    env=dict(os.environ,XDG_CONFIG_HOME=temp+'/config',XDG_DATA_HOME=temp+'/data',XDG_STATE_HOME=temp+'/state')
    for mime in browser_mimes:
        assert run('xdg-mime','query','default',mime,env=env).strip()==browsers['epiphany'],mime
    for browser,app in browsers.items():
        if not shutil.which(browser):continue
        run('rpd-user-settings','browser',browser,env=env)
        assert run('rpd-user-settings','get-browser',env=env).strip()==app
        for mime in browser_mimes:
            assert run('xdg-mime','query','default',mime,env=env).strip()==app,(browser,mime)
            result=run('gio','mime',mime,env=env)
            assert app in result and 'No default applications' not in result,(browser,mime,result)
with tempfile.TemporaryDirectory() as temp:
    p=pathlib.Path(temp);(p/'test.txt').write_text('RPD archive round trip\n')
    run('zip','-q','test.zip','test.txt',cwd=temp)
    assert run('unzip','-p','test.zip','test.txt',cwd=temp)=='RPD archive round trip\n'
    run('7z','a','test.7z','test.txt',cwd=temp)
    assert run('7z','x','-so','test.7z','test.txt',cwd=temp)=='RPD archive round trip\n'
if shutil.which('chromium'):
    prefs=json.loads(pathlib.Path('/usr/lib/chromium/initial_preferences').read_text())
    assert prefs['extensions']['theme']['use_system']
    assert 'initial_extensions' not in prefs
    assert prefs['distribution']['require_eula'] is False
    flags=run('sh','-c','for f in /etc/chromium/*.conf; do . "$f"; done; printf "%s" "$CHROMIUM_FLAGS"')
    assert '--ozone-platform=wayland' in flags and '--enable-wayland-ime' in flags,flags
    policy=json.loads(pathlib.Path('/etc/chromium/policies/recommended/rpd.json').read_text())
    assert policy['DefaultSearchProviderName']=='DuckDuckGo'
    assert pathlib.Path(prefs['distribution']['import_bookmarks_from_file']).is_file()
print('GIO associations, GNOME Web defaults, installed browser choices and ZIP/7z round trips passed')
