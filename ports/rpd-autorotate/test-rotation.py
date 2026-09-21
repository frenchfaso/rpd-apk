import unittest
from rotation import RotationPolicy
class RotationTests(unittest.TestCase):
    def test_jitter_and_flat_cancel(self):
        p=RotationPolicy()
        p.observe('normal','vertical',0)
        p.observe('left-up','vertical',0.4)
        self.assertIsNone(p.due(0.9))
        p.observe('left-up','face-up',1)
        self.assertIsNone(p.due(2))
    def test_stable_samples_dont_delay(self):
        p=RotationPolicy()
        p.observe('normal','vertical',0)
        p.observe('normal','tilted-up',0.5)
        self.assertEqual(p.due(0.81),'normal')
    def test_manual_keyboard_choice_preserved_until_aspect_change(self):
        p=RotationPolicy()
        self.assertTrue(p.committed('normal',True))
        self.assertIsNone(p.committed('bottom-up',True))
        self.assertFalse(p.committed('left-up',False))
        self.assertIsNone(p.committed('right-up',False))
        self.assertTrue(p.committed('normal',True))
    def test_return_to_applied_cancels_transient(self):
        p=RotationPolicy();p.committed('normal',True)
        p.observe('left-up','vertical',0)
        p.observe('normal','vertical',0.5)
        self.assertIsNone(p.due(2))
    def test_undefined_never_rotates(self):
        p=RotationPolicy();p.observe('undefined','vertical',0)
        self.assertIsNone(p.due(1))
unittest.main()
