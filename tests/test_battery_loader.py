import importlib.machinery
import importlib.util
import pathlib
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


class BatteryLoaderTests(unittest.TestCase):
    def setUp(self):
        path=pathlib.Path(__file__).parents[1]/'ports/rpd-backlight-m10/rpd-battery-m10-load'
        loader=importlib.machinery.SourceFileLoader('battery_loader',str(path))
        spec=importlib.util.spec_from_loader(loader.name,loader)
        self.module=importlib.util.module_from_spec(spec);loader.exec_module(self.module)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        root=pathlib.Path(self.temp.name)
        self.module.DEVICE=root/'adc';self.module.DEVICE.mkdir()
        self.module.SUPPLIES=root/'supplies';self.module.SUPPLIES.mkdir()
        self.calls=[];self.current=self.module.ORIGINAL

    def run_cmd(self,*args,**kwargs):
        self.calls.append(args)
        return SimpleNamespace(returncode=0,stdout='')

    def write(self,path,value):
        if path.name=='unbind': self.current=None
        elif path.name=='bind': self.current=path.parent.name

    def test_kernel_mismatch_touches_nothing(self):
        with patch.object(self.module,'matching',return_value=False), patch.object(self.module,'run',self.run_cmd), patch.object(self.module.sys,'argv',['loader']):
            self.module.main()
        self.assertEqual(self.calls,[])

    def test_failed_temperature_restores_original_and_otg(self):
        with patch.object(self.module,'matching',return_value=True), patch.object(self.module,'run',self.run_cmd), patch.object(self.module,'driver',side_effect=lambda:self.current), patch.object(self.module,'write',self.write), patch.object(self.module.sys,'argv',['loader']):
            with self.assertRaises(FileNotFoundError):self.module.main()
        self.assertEqual(self.current,self.module.ORIGINAL)
        self.assertIn(('modprobe','-r','m10_battery'),self.calls)
        self.assertIn(('systemctl','start','--no-block','rpd-usb-otg-m10.service'),self.calls)

    def test_native_battery_is_not_replaced(self):
        path=self.module.SUPPLIES/'native';path.mkdir();(path/'type').write_text('Battery\n')
        with patch.object(self.module,'matching',return_value=True), patch.object(self.module,'run',self.run_cmd), patch.object(self.module.sys,'argv',['loader']):
            self.module.main()
        self.assertEqual(self.calls,[])

if __name__=='__main__': unittest.main()
