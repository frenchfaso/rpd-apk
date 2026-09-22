#!/usr/bin/python3
"""Session-scoped SensorProxy to wlroots/Squeekboard integration."""
import argparse, configparser, json, os, pathlib, signal, subprocess, time
from rotation import RotationPolicy, TRANSFORMS
from touchmap import configure as configure_touch

config_home = pathlib.Path(os.environ.get('XDG_CONFIG_HOME', str(pathlib.Path.home()/'.config')))
settings_dir = config_home/'rpd'
settings_dir.mkdir(parents=True, exist_ok=True)
disabled = settings_dir/'autorotate-disabled'
parser = argparse.ArgumentParser()
parser.add_argument('--greeter', action='store_true', help='Rotate the active login screen and enable its keyboard only in portrait')
actions = parser.add_mutually_exclusive_group()
for name in ('enable', 'disable', 'status', 'reset-touch'):
    actions.add_argument('--'+name, action='store_true')
args = parser.parse_args()
if args.enable or args.disable or args.status:
    if args.enable: disabled.unlink(missing_ok=True)
    if args.disable: disabled.touch()
    print('disabled' if disabled.exists() else 'enabled')
    raise SystemExit(0)

config = configparser.ConfigParser()
config.read([os.environ.get('RPD_AUTOROTATE_CONFIG', '/etc/xdg/rpd/autorotate.conf'), str(settings_dir/'autorotate.conf')])
output = config.get('rotation', 'output')
rotation_map = {key: config.get('rotation', key, fallback=value) for key, value in TRANSFORMS.items()}
if any(value not in ('normal', '90', '180', '270') for value in rotation_map.values()):
    raise ValueError('Unsupported output transform')
touch_device = config.get('rotation', 'touch_device', fallback='')
base_matrix = tuple(float(x) for x in config.get('rotation', 'touch_matrix', fallback='1 0 0 0 1 0').split())
if len(base_matrix) != 6: raise ValueError('Touch matrix requires six values')
rc_path = pathlib.Path(os.environ.get('RPD_CONFIG_DIR', str(config_home/'labwc')))/'rc.xml'
if args.reset_touch:
    configure_touch(rc_path, touch_device, output, base_matrix)
    raise SystemExit(0)

import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio, GLib

policy = RotationPolicy(max(0.2, min(3, config.getfloat('rotation', 'delay', fallback=0.8))))
SENSOR = 'net.hadess.SensorProxy'
SENSOR_PATH = '/net/hadess/SensorProxy'
claimed = False
pending_timer = None
session = None
loop = GLib.MainLoop()

def proxy(name, path, interface):
    return Gio.DBusProxy.new_for_bus_sync(Gio.BusType.SYSTEM, Gio.DBusProxyFlags.NONE, None, name, path, interface, None)

def value(obj, key, default=None):
    prop = obj.get_cached_property(key) if obj else None
    return prop.unpack() if prop is not None else default

def call(obj, method):
    return obj.call_sync(method, None, Gio.DBusCallFlags.NONE, 3000, None)

def clear_pending():
    global pending_timer
    policy.cancel()
    if pending_timer is not None:
        GLib.source_remove(pending_timer)
        pending_timer = None

def apply():
    global pending_timer
    pending_timer = None
    orientation = policy.due(time.monotonic())
    if orientation is None or not claimed:
        return GLib.SOURCE_REMOVE
    try:
        outputs = json.loads(subprocess.check_output(['wlr-randr', '--json'], text=True, timeout=3))
        target = next((item for item in outputs if item['name'] == output and item['enabled']), None)
        if target is None:
            raise RuntimeError('Configured display is unavailable')
        transform = rotation_map[orientation]
        previous = target['transform']
        try:
            if configure_touch(rc_path, touch_device, output, base_matrix):
                subprocess.run(['labwc', '--reconfigure'], check=True, timeout=3)
            if previous != transform:
                subprocess.run(['wlr-randr', '--output', output, '--transform', transform], check=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            if configure_touch(rc_path, touch_device, output, base_matrix):
                subprocess.run(['labwc', '--reconfigure'], check=True, timeout=3)
            raise
        mode = next(mode for mode in target['modes'] if mode.get('current'))
        width, height = mode['width'], mode['height']
        if transform in ('90', '270'): width, height = height, width
        keyboard = policy.committed(orientation, height > width)
        if keyboard is not None:
            if args.greeter:
                Gio.Settings.new('org.gnome.desktop.a11y.applications').set_boolean('screen-keyboard-enabled', keyboard)
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            bus.call_sync('sm.puri.OSK0', '/sm/puri/OSK0', 'sm.puri.OSK0', 'SetVisible',
                          GLib.Variant('(b)', (keyboard,)), None, Gio.DBusCallFlags.NONE, 3000, None)
        print(f'{orientation}: transform={transform}, keyboard={keyboard}', flush=True)
    except (GLib.Error, OSError, subprocess.SubprocessError, RuntimeError, StopIteration, KeyError) as error:
        print('Rotation not applied:', error, flush=True)
        policy.cancel()
    return GLib.SOURCE_REMOVE

def orientation_changed(*unused):
    global pending_timer
    if not claimed: return
    policy.observe(value(sensor, 'AccelerometerOrientation'), value(sensor, 'AccelerometerTilt'), time.monotonic())
    if pending_timer is not None:
        GLib.source_remove(pending_timer)
        pending_timer = None
    if policy.pending:
        delay = max(1, int((policy.deadline-time.monotonic())*1000)+1)
        pending_timer = GLib.timeout_add(delay, apply)

def reconcile(*unused):
    global claimed
    wanted = (not disabled.exists() and value(session, 'Active', False)
              and not value(session, 'Remote', True) and not value(session, 'LockedHint', False)
              and value(sensor, 'HasAccelerometer', False))
    if args.greeter:
        wanted = wanted and value(session, 'Class') == 'greeter'
    if not sensor.get_name_owner():
        claimed = False
    try:
        if wanted and not claimed:
            call(sensor, 'ClaimAccelerometer')
            claimed = True
            orientation_changed()
        elif not wanted and claimed:
            call(sensor, 'ReleaseAccelerometer')
            claimed = False
    except GLib.Error as error:
        print('Sensor access:', error.message, flush=True)
    if not wanted: clear_pending()

def display_session_changed(*unused):
    global session
    display = value(user, 'Display', ('', '/'))
    session = proxy('org.freedesktop.login1', display[1], 'org.freedesktop.login1.Session') if display[0] else None
    if session: session.connect('g-properties-changed', reconcile)
    reconcile()

def stop(*unused):
    clear_pending()
    if claimed:
        try: call(sensor, 'ReleaseAccelerometer')
        except GLib.Error: pass
    loop.quit()
    return GLib.SOURCE_REMOVE

sensor = proxy(SENSOR, SENSOR_PATH, SENSOR)
sensor.connect('g-properties-changed', lambda *a: (reconcile(), orientation_changed()))
sensor.connect('notify::g-name-owner', reconcile)
# User.Display identifies the local graphical session even for systemd user units.
user = proxy('org.freedesktop.login1', '/org/freedesktop/login1/user/_'+str(os.getuid()), 'org.freedesktop.login1.User')
user.connect('g-properties-changed', display_session_changed)
monitor = Gio.File.new_for_path(str(settings_dir)).monitor_directory(Gio.FileMonitorFlags.NONE, None)
monitor.connect('changed', reconcile)
display_session_changed()
for sig in (signal.SIGINT, signal.SIGTERM): GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop)
try: loop.run()
finally: stop()
