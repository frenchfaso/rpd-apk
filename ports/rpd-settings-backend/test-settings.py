import importlib.machinery,sys
module=importlib.machinery.SourceFileLoader('settings',sys.argv[1]).load_module()
valid={'action':'displays','kanshi':'profile {\noutput Unknown-1 enable scale 1.0 mode 800x1280@60.000 position 0,0 transform normal\n}\n','touch':'<labwc_config><touch deviceName="Goodix" mapToOutput="Unknown-1" mouseEmulation="no"/><keyboard><keybind key="x"><action name="Execute" command="bad"/></keybind></keyboard></labwc_config>'}
result=module.validate(valid)
assert result['touch']==[{'deviceName':'Goodix','mapToOutput':'Unknown-1','mouseEmulation':'no'}]
assert 'Execute' not in str(result)
module.validate({'action':'appearance','theme':'PiXonyx','font':'Nunito Sans Light 12'})
for request in [dict(valid,kanshi='profile {\nexec touch /tmp/no\n}\n'),dict(valid,kanshi='profile {\noutput Unknown-1 disable\n}\n'),dict(valid,touch='<!DOCTYPE foo><labwc_config/>'),{'action':'appearance','theme':'../../tmp/theme','font':'Sans 12'},{'action':'appearance','theme':'PiXtrix','font':'Sans\nx=evil'},{'action':'copy','path':'/etc/passwd'}]:
 try:module.validate(request)
 except (ValueError,KeyError):pass
 else:raise AssertionError(request)
print('Greeter validation: fixed settings accepted; commands, declarations and paths rejected')
