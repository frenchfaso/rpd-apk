"""Update only the configured touchscreen's labwc mapping, atomically."""
import os, pathlib, tempfile, xml.etree.ElementTree as ET

def configure(path, device, output, base=(1, 0, 0, 0, 1, 0)):
    if not device: return False
    path = pathlib.Path(path)
    for attempt in range(3):
        original = path.read_bytes()
        root = ET.fromstring(original, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True)))
        ns = root.tag.partition('}')[0]+'}' if root.tag.startswith('{') else ''
        if ns: ET.register_namespace('', ns[1:-1])
        def child(parent, name):
            item = parent.find(ns+name)
            return item if item is not None else ET.SubElement(parent, ns+name)
        libinput = child(root, 'libinput')
        profile = next((p for p in libinput.findall(ns+'device') if p.get('category') == device), None)
        if profile is None: profile = ET.SubElement(libinput, ns+'device', category=device)
        calibration = child(profile, 'calibrationMatrix')
        matrix = ' '.join(format(v, '.8g') for v in base)
        touch = next((t for t in root.findall(ns+'touch') if t.get('deviceName') == device), None)
        if touch is None: touch = ET.SubElement(root, ns+'touch', deviceName=device)
        if calibration.text == matrix and touch.get('mapToOutput') == output: return False
        calibration.text = matrix
        touch.set('mapToOutput', output)
        data = ET.tostring(root, encoding='UTF-8', xml_declaration=True)
        fd, temp = tempfile.mkstemp(prefix='.rpd-touch-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream: stream.write(data)
            os.chmod(temp, path.stat().st_mode & 0o777)
            # Avoid replacing a preference editor's intervening save.
            if path.read_bytes() != original: continue
            os.replace(temp, path)
            return True
        finally:
            if os.path.exists(temp): os.unlink(temp)
    raise RuntimeError('Touch configuration changed concurrently; retry rotation')
