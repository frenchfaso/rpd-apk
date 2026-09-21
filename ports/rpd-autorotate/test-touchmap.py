import pathlib, tempfile, unittest, xml.etree.ElementTree as ET
from touchmap import configure
class TouchMapping(unittest.TestCase):
    def test_preserve_settings_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            p=pathlib.Path(d)/'rc.xml'
            p.write_text('<openbox_config xmlns="http://openbox.org/3.4/rc"><!--keep--><theme><name>Custom</name></theme><libinput><device category="mouse"><leftHanded>yes</leftHanded></device></libinput></openbox_config>')
            self.assertTrue(configure(p,'Goodix','Unknown-1'))
            self.assertFalse(configure(p,'Goodix','Unknown-1'))
            root=ET.parse(p).getroot();ns={'x':'http://openbox.org/3.4/rc'}
            self.assertEqual(root.findtext('x:theme/x:name',namespaces=ns),'Custom')
            self.assertEqual(root.findtext('x:libinput/x:device[@category="mouse"]/x:leftHanded',namespaces=ns),'yes')
            self.assertEqual(root.findtext('x:libinput/x:device[@category="Goodix"]/x:calibrationMatrix',namespaces=ns),'1 0 0 0 1 0')
            self.assertEqual(len(root.findall('x:touch',ns)),1)
            self.assertIn('<!--keep-->',p.read_text())
unittest.main()
