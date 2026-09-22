#!/usr/bin/env python3
from pathlib import Path
import re,json,hashlib,argparse,subprocess
p=argparse.ArgumentParser(description="Extract OEM QG voltage/SOC profiles from the stock Lenovo DTB")
p.add_argument("dtb",type=Path);p.add_argument("output",type=Path);args=p.parse_args()
s=subprocess.check_output(['dtc','-I','dtb','-O','dts',str(args.dtb)],text=True)
out={'source':'Lenovo TB-X505L stock boot-dtb-1.dtb; OEM profile version 100', 'dtb_sha256':hashlib.sha256(args.dtb.read_bytes()).hexdigest(),'voltage_unit':'microvolt','soc_unit':'percent','profiles':{}}
for key,node in [('atl','qcom,atl_4850mah'),('lwn','qcom,sunwoda_4850mah')]:
 start=s.index(node+' {'); pos=start+s[start:].index('{')+1; depth=1;end=pos
 while depth:
  if s[end]=='{':depth+=1
  if s[end]=='}':depth-=1
  end+=1
 block=s[pos:end-1]
 def vals(b,name):
  raw=re.search(re.escape(name)+r' = <([^>]+)>;',b).group(1)
  ns=[int(v,0) for v in raw.split()]
  return [n-2**32 if n>=2**31 else n for n in ns]
 profile={'battery_id_kohm':vals(block,'qcom,batt-id-kohm')[0],'nominal_mah':4850}
 for phase,num in [('charging',1),('discharging',2)]:
  b=re.search(r'qcom,pc-temp-v'+str(num)+r'-lut \{(.*?)\n\s*\};',block,re.S).group(1)
  temps=vals(b,'qcom,lut-col-legend');soc=[n/100 for n in vals(b,'qcom,lut-row-legend')];vs=[v*100 for v in vals(b,'qcom,lut-data')]
  assert len(vs)==len(temps)*len(soc)
  profile[phase]={'temperatures':temps,'soc':soc,'voltage_uv':[vs[i*len(temps):(i+1)*len(temps)] for i in range(len(soc))]}
 out['profiles'][key]=profile
args.output.write_text(json.dumps(out,indent=2)+'\n')
print({k:(len(p['discharging']['soc']), p['battery_id_kohm']) for k,p in out['profiles'].items()})
