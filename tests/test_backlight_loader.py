import os,pathlib,subprocess,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
LOADER=ROOT/'ports/rpd-backlight-m10/rpd-backlight-m10-load'
class LoaderTests(unittest.TestCase):
    def run_loader(self,release_match=True,apk_match=True,modprobe_ok=True):
        expected=next(s.split('=',1)[1] for s in LOADER.read_text().splitlines() if s.startswith('expected='))
        with tempfile.TemporaryDirectory() as tmp:
            root=pathlib.Path(tmp)
            scripts={'uname':'printf "%s\\n" "$MOCK_RELEASE"',
                     'apk':'exit "$MOCK_APK_STATUS"',
                     'modprobe':'touch "$MOCK_CALLED"; exit "$MOCK_MODULE_STATUS"'}
            for name,body in scripts.items():
                p=root/name;p.write_text('#!/bin/sh\n'+body+'\n');p.chmod(0o755)
            env=dict(os.environ,PATH=tmp+':'+os.environ['PATH'],MOCK_RELEASE=expected if release_match else 'future-kernel',
                     MOCK_APK_STATUS='0' if apk_match else '1',MOCK_MODULE_STATUS='0' if modprobe_ok else '1',MOCK_CALLED=str(root/'called'))
            result=subprocess.run(['sh',str(LOADER)],env=env,capture_output=True,text=True)
            return result,(root/'called').exists()
    def test_new_kernel_skips_module_successfully(self):
        result,called=self.run_loader(release_match=False)
        self.assertEqual(result.returncode,0);self.assertFalse(called)
    def test_new_revision_same_release_skips_module(self):
        result,called=self.run_loader(apk_match=False)
        self.assertEqual(result.returncode,0);self.assertFalse(called)
    def test_matching_kernel_loads_module(self):
        result,called=self.run_loader()
        self.assertEqual(result.returncode,0);self.assertTrue(called)
    def test_module_rejection_does_not_fail_boot_service(self):
        result,called=self.run_loader(modprobe_ok=False)
        self.assertEqual(result.returncode,0);self.assertTrue(called);self.assertIn('unavailable',result.stderr)
if __name__=='__main__':unittest.main()
