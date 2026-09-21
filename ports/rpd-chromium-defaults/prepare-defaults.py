#!/usr/bin/python3
"""Keep upstream user defaults; omit Pi codec/remote extension installation."""
import json,pathlib,shutil,sys
source,dest=map(pathlib.Path,sys.argv[1:])
prefs=json.loads((source/'armhf/initial_preferences').read_text())
prefs.pop('initial_extensions',None)
# Unbranded Alpine Chromium otherwise shows an empty additional-terms dialog.
prefs['distribution']['require_eula']=False
prefs['distribution']['import_bookmarks_from_file']='/usr/share/rpd-chromium/bookmarks.html'
for path in ['usr/lib/chromium','usr/share/rpd-chromium','etc/chromium/policies/recommended']:
    (dest/path).mkdir(parents=True,exist_ok=True)
(dest/'usr/lib/chromium/initial_preferences').write_text(json.dumps(prefs,indent=2)+'\n')
shutil.copyfile(source/'armhf/bookmarks.html',dest/'usr/share/rpd-chromium/bookmarks.html')
search=prefs['default_search_provider_data']['template_url_data']
recommended={'DefaultSearchProviderEnabled':True,'DefaultSearchProviderName':search['short_name'],'DefaultSearchProviderSearchURL':search['url'],'SearchSuggestEnabled':False,'BookmarkBarEnabled':True}
(dest/'etc/chromium/policies/recommended/rpd.json').write_text(json.dumps(recommended,indent=2)+'\n')
