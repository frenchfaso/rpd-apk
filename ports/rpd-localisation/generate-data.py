#!/usr/bin/env python3
"""Adapt current Alpine locale/XKB data to the upstream dialog's data format."""
import json,pathlib,re,subprocess,sys,xml.etree.ElementTree as ET
out=pathlib.Path(sys.argv[1]);(out/'locales').mkdir(parents=True,exist_ok=True)
countries={x['alpha_2']:x['name'] for x in json.load(open('/usr/share/iso-codes/json/iso_3166-1.json'))['3166-1']}
languages={}
for x in json.load(open('/usr/share/iso-codes/json/iso_639-3.json'))['639-3']:
 for key in ['alpha_2','alpha_3']:
  if key in x:languages[x[key]]=x['name']
rows=[]
for loc in subprocess.check_output(['locale','-a'],text=True).splitlines():
 base=loc.split('.')[0]
 if not re.fullmatch(r'[a-z]{2,3}_[A-Z]{2}',base):continue
 lang,country=base.split('_')
 rows.append(base+'.UTF-8 UTF-8\n')
 (out/'locales'/base).write_text('language "'+languages.get(lang,lang)+'"\nterritory "'+countries.get(country,country)+'"\n')
(out/'SUPPORTED').write_text(''.join(sorted(set(rows))))
xkb=ET.parse('/usr/share/X11/xkb/rules/evdev.xml')
def pair(node):
 name=node.findtext('configItem/name');desc=node.findtext('configItem/description',name).replace("'",'’').replace('\n',' ')
 return desc,name
lines=[]
for section,tag in [('models','model'),('layouts','layout')]:
 lines.append('%'+section+' = (\n')
 for node in xkb.findall('.//'+tag+'List/'+tag):
  desc,name=pair(node);lines.append("    '%s' => '%s',\n"%(desc,name))
 lines.append(');\n')
lines.append('%variants = (\n')
for node in xkb.findall('.//layoutList/layout'):
 desc,name=pair(node);lines.append("    '%s' => {\n"%name)
 for variant in node.findall('variantList/variant'):
  desc,name=pair(variant);lines.append("        '%s' => '%s',\n"%(desc,name))
 lines.append('    },\n')
lines.append(');\n');(out/'KeyboardNames.pl').write_text(''.join(lines))
