import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class GpuLoaderTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1]/'ports/rpd-backlight-m10/rpd-gpu-m10-load'
        loader = importlib.machinery.SourceFileLoader('gpu_loader', str(path))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        self.m = importlib.util.module_from_spec(spec)
        loader.exec_module(self.m)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root/'usr/lib/rpd-gpu-m10'
        self.data.mkdir(parents=True)
        (self.data/'kernel.json').write_text(json.dumps({'release':'verified', 'apk':'1-r0'}))
        self.compatible = self.root/'proc/device-tree/soc@0/gpu@1c00000/compatible'
        self.compatible.parent.mkdir(parents=True)
        self.compatible.write_bytes(b'qcom,adreno-504.0\0qcom,adreno\0')

    def run_loader(self, release='verified', apk_match=True):
        calls = []
        with patch.object(self.m, 'Path', lambda p: self.root/str(p).lstrip('/')), \
             patch.object(self.m.subprocess, 'check_output', return_value=release), \
             patch.object(self.m.subprocess, 'run', return_value=SimpleNamespace(returncode=0 if apk_match else 1)), \
             patch.object(self.m, 'run', lambda *args: calls.append(args)):
            self.m.main()
        return calls

    def test_new_kernel_never_loads_old_extension(self):
        self.assertEqual(self.run_loader(release='future'),
                         [('modprobe', 'msm', 'separate_gpu_kms=1')])

    def test_same_release_different_apk_never_loads_old_extension(self):
        self.assertEqual(self.run_loader(apk_match=False),
                         [('modprobe', 'msm', 'separate_gpu_kms=1')])

    def test_old_device_tree_does_not_load_extension(self):
        self.compatible.write_bytes(b'qcom,adreno-505.0\0qcom,adreno\0')
        self.assertEqual(self.run_loader(), [])

    def test_never_unloads_a_live_driver(self):
        (self.root/'sys/module/msm').mkdir(parents=True)
        self.assertEqual(self.run_loader(), [])

    def test_loads_private_modules_and_upstream_dependencies(self):
        calls = self.run_loader()
        self.assertEqual(calls[0], ('insmod', str(self.data/'ubwc_config.ko')))
        self.assertEqual(calls[-1], ('insmod', str(self.data/'msm.ko'), 'separate_gpu_kms=1'))
        self.assertTrue(all(c[0] == 'modprobe' for c in calls[1:-1]))
        self.assertIn(('modprobe', 'mdt_loader'), calls)
        self.assertNotIn(('modprobe', 'qcom_mdt_loader'), calls)
