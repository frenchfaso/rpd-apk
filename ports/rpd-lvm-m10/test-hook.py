import os
from pathlib import Path
import subprocess
import tempfile
import unittest

HOOK=Path(__file__).with_name('20-rpd-lvm-m10.sh').read_text()

class HookTests(unittest.TestCase):
    def run_hook(self, config=None, board='lenovo,tbx505x', loop='/dev/loop9', fail=False):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'compatible').write_bytes(board.encode()+b'\0')
            if config is not None:(root/'config').write_text(config)
            source=HOOK.replace('/etc/rpd-lvm-m10.conf',str(root/'config')).replace('/proc/device-tree/compatible',str(root/'compatible'))
            # Block-device existence is exercised with real loop devices by
            # tests/test_lvm_native.sh. Mock only this predicate in host tests.
            source=source.replace('[ -b "$userdata" ]','true').replace('[ -b "$system" ]','true')
            source=source.replace('[ -b "${loop}p1" ]','true').replace('[ -b "${loop}p2" ]','true')
            (root/'hook').write_text(source)
            (root/'readlink').write_text('#!/bin/sh\nprintf "%s\\n" "$2"\n')
            (root/'losetup').write_text('#!/bin/sh\nprintf "%s\\n" "'+loop+'"\n')
            (root/'lvm').write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$CALLS"\nexit '+str(int(fail))+'\n')
            for cmd in ('readlink','losetup','lvm'):(root/cmd).chmod(0o755)
            p=subprocess.run(['sh',str(root/'hook')],env={**os.environ,'PATH':tmp+':'+os.environ['PATH'],'CALLS':str(root/'calls')},capture_output=True,text=True)
            return p.returncode,(root/'calls').read_text() if (root/'calls').exists() else ''

    config='userdata_partuuid=11111111-1111-1111-1111-111111111111\nsystem_partuuid=22222222-2222-2222-2222-222222222222\nvolume_group=m10linux\n'
    def test_unconfigured_or_other_board_does_nothing(self):
        self.assertEqual(self.run_hook(),(0,''))
        self.assertEqual(self.run_hook(self.config,board='other,board'),(0,''))
    def test_valid_activation_is_complete_and_device_scoped(self):
        status,args=self.run_hook(self.config)
        self.assertEqual(status,0)
        self.assertIn('--activationmode\ncomplete\n',args)
        self.assertIn('/dev/loop9p2',args)
        self.assertIn('udev_sync=0',args)
        self.assertTrue(args.endswith('m10linux\n'))
    def test_invalid_group_or_partition_never_activates(self):
        for text in (self.config.replace('m10linux','../other'),self.config.replace('11111111-','../11111111-',1)):
            status,args=self.run_hook(text);self.assertNotEqual(status,0);self.assertEqual(args,'')
    def test_multiple_loop_mappings_are_rejected(self):
        status,args=self.run_hook(self.config,loop='/dev/loop1\n/dev/loop2')
        self.assertNotEqual(status,0);self.assertEqual(args,'')
    def test_activation_failure_is_not_ignored(self):
        status,_=self.run_hook(self.config,fail=True);self.assertNotEqual(status,0)

if __name__=='__main__':unittest.main()
