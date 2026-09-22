import json
import pathlib
import unittest
from power_model import Model, curve_soc, select_profile

PROFILES = json.loads(pathlib.Path(__file__).with_name('m10-profiles.json').read_text())['profiles']


def sample(**kwargs):
    p = PROFILES['atl']['discharging']
    v = p['voltage_uv'][p['soc'].index(50)][p['temperatures'].index(25)]
    return dict(voltage_uv=v, current_ua=-485000, temp_c=25, elapsed=0, timestamp=100000,
                boot_id='boot1', id_uv=674400, usb_online=False, charger_state=7,
                float_voltage_uv=4350000, **kwargs)


class ModelTests(unittest.TestCase):
    def test_oem_units_profiles_and_curve(self):
        self.assertEqual(select_profile(PROFILES, 674400), 'atl')
        self.assertEqual(select_profile(PROFILES, 325413), 'lwn')
        self.assertEqual(PROFILES['atl']['charging']['voltage_uv'][0][2], 4381800)
        for p in PROFILES.values():
            for charging in (False, True):
                for temp in range(-10, 51):
                    value = curve_soc(p, 4000000, temp, charging)
                    self.assertTrue(0 <= value <= 100)

    def test_one_hour_integrates_485mah_as_ten_percent(self):
        model = Model(PROFILES)
        reading = sample()
        self.assertEqual(model.update(reading)['percentage'], 50)
        for n in range(1, 241):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            result = model.update(reading)
        self.assertAlmostEqual(model.state['soc'], 40, places=7)
        self.assertTrue(result['estimated'])
        self.assertAlmostEqual(result['time_to_empty_seconds'], 14400, delta=1)
        self.assertIsNone(result['time_to_full_seconds_at_current_rate'])

    def test_gap_or_reboot_never_integrates_missing_current(self):
        model = Model(PROFILES)
        reading = sample()
        model.update(reading)
        reading.update(elapsed=3600, timestamp=103600)
        result = model.update(reading)
        self.assertEqual(result['percentage'], 50)
        self.assertEqual(result['method'], 'voltage-seed')
        self.assertIsNone(result['time_to_empty_seconds'])
        reading.update(elapsed=0, boot_id='boot2')
        self.assertEqual(model.update(reading)['percentage'], 50)

    def test_full_requires_real_termination_for_five_minutes(self):
        reading = sample()
        reading.update(voltage_uv=4350000, current_ua=0, usb_online=True, charger_state=3)
        model = Model(PROFILES)
        for n in range(30):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            result = model.update(reading)
        self.assertLess(result['percentage'], 100)
        reading['charger_state'] = 5
        for n in range(30, 51):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            result = model.update(reading)
        self.assertEqual(result['percentage'], 100)
        self.assertEqual(result['full_references'], 1)
        reading['elapsed'] += 15
        self.assertEqual(model.update(reading)['full_references'], 1)

    def test_brief_reboot_preserves_estimate_without_integrating_missing_time(self):
        model = Model(PROFILES)
        reading = sample()
        model.update(reading)
        reading.update(boot_id='boot2', elapsed=20, timestamp=100060, voltage_uv=3500000)
        result = model.update(reading)
        self.assertEqual(result['percentage'], 50)
        self.assertEqual(result['method'], 'last-estimate-after-gap')
        self.assertIsNone(result['time_to_empty_seconds'])
        self.assertIsNone(model.state['anchor_net_mah'])

    def test_charge_eta_requires_stable_rate_and_resets_on_unplug(self):
        reading = sample()
        reading.update(current_ua=485000, usb_online=True, charger_state=3)
        model = Model(PROFILES)
        for n in range(13):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            result = model.update(reading)
            if n < 12:
                self.assertIsNone(result['time_to_full_seconds_at_current_rate'])
        expected = 4850 * (100-model.state['soc']) / 100 / 485 * 3600
        self.assertAlmostEqual(result['time_to_full_seconds_at_current_rate'], expected, delta=1)
        reading.update(elapsed=195, current_ua=-485000, usb_online=False)
        result = model.update(reading)
        self.assertIsNone(result['time_to_full_seconds_at_current_rate'])
        self.assertIsNone(result['time_to_empty_seconds'])

    def test_invalid_data_never_becomes_zero_percent(self):
        for field, value in [('voltage_uv', 0), ('current_ua', float('nan')),
                             ('temp_c', 100), ('id_uv', 1)]:
            reading = sample(); reading[field] = value
            with self.assertRaises(ValueError):
                Model(PROFILES).update(reading)


if __name__ == '__main__':
    unittest.main()
