import importlib.util
import io
import pathlib
import shutil
import tempfile
import unittest
from unittest.mock import patch

ROOT=pathlib.Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('updater',ROOT/'scripts/update-m10-kernel.py')
u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)

class KernelUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=pathlib.Path(self.temp.name)
        self.port=self.root/'port'
        shutil.copytree(ROOT/'ports/rpd-backlight-m10',self.port,
                        ignore=shutil.ignore_patterns('src','pkg','*.tar.*'))
        self.config=(self.port/'kernel.config').read_text()
        self.recipe=(self.port/'upstream-APKBUILD.reference').read_text()
        self.old_ver=u.field(self.recipe,'pkgver')
        self.old_package=self.old_ver+'-r'+u.field(self.recipe,'pkgrel')
        parts=self.old_ver.split('.'); parts[-1]=str(int(parts[-1])+1)
        self.new_ver='.'.join(parts)
        self.version=self.new_ver+'-r0'
        self.patches=[patch.object(u,'PORT',self.port), patch.object(u,'ROOT',self.root),
                      patch.object(u.subprocess,'run',side_effect=self.fake_run),
                      patch.object(u.subprocess,'check_output',return_value='>\n'),
                      patch.object(u,'read_package',side_effect=lambda _:('pkgver = '+self.version+'\n',self.config)),
                      patch.object(u.urllib.request,'urlopen',side_effect=lambda *a,**kw:io.BytesIO(self.recipe.encode()))]
        for p in self.patches:p.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(lambda:[p.stop() for p in reversed(self.patches)])
    def fake_run(self,args,**kwargs):
        if 'fetch' in args:
            pathlib.Path(args[args.index('--output')+1],u.PACKAGE+'-'+self.version+'.apk').touch()
    def test_new_kernel_updates_dependency_source_loader_and_hashes(self):
        self.recipe=self.recipe.replace('pkgver='+self.old_ver,'pkgver='+self.new_ver).replace('pkgrel='+u.field(self.recipe,'pkgrel'),'pkgrel=0')
        self.config=self.config.replace(self.old_ver,self.new_ver)
        u.main()
        text=(self.port/'APKBUILD').read_text()
        self.assertIn('_kernel_apk_version='+self.new_ver+'-r0',text)
        self.assertNotIn('depends="linux-postmarketos',text)
        self.assertIn('linux-v'+self.new_ver+'-r1.tar.gz',text)
        self.assertIn('expected='+self.new_ver+'-msm89x7',(self.port/'rpd-backlight-m10-load').read_text())
        for name in ['kernel.config','rpd-backlight-m10-load']:
            self.assertIn(u.hashlib.sha512((self.port/name).read_bytes()).hexdigest()+'  '+name,text)
    def test_same_version_config_change_is_rejected(self):
        self.version=self.old_package; self.config+='\nCONFIG_UNREVIEWED=y\n'
        with self.assertRaisesRegex(ValueError,'without an APK version bump'):u.main()
    def test_new_patch_in_recipe_requires_review(self):
        self.recipe=self.recipe.replace('pkgver='+self.old_ver,'pkgver='+self.new_ver).replace('pkgrel='+u.field(self.recipe,'pkgrel'),'pkgrel=0')+'\n# New source patch\n'
        with self.assertRaisesRegex(ValueError,'recipe changed'):u.main()
    def test_binary_source_version_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'binary and upstream recipe differ'):u.main()
    def test_unchanged_kernel_does_not_rewrite_port(self):
        self.version=self.old_package
        before=(self.port/'APKBUILD').read_bytes()
        u.main()
        self.assertEqual(before,(self.port/'APKBUILD').read_bytes())

if __name__=='__main__':unittest.main()
