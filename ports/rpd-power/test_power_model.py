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
        self.assertIsNone(model.update(reading)['percentage'])
        for n in range(1, 241):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            result = model.update(reading)
        self.assertAlmostEqual(model.state['soc'], 40.5, places=7)
        self.assertTrue(result['estimated'])
        self.assertAlmostEqual(result['time_to_empty_seconds'], 14580, delta=1)
        self.assertIsNone(result['time_to_full_seconds_at_current_rate'])

    def test_gap_or_reboot_never_integrates_missing_current(self):
        model = Model(PROFILES)
        reading = sample()
        model.update(reading)
        reading.update(elapsed=3600, timestamp=103600)
        result = model.update(reading)
        self.assertIsNone(result['percentage'])
        self.assertEqual(result['method'], 'collecting-voltage-seed')
        self.assertIsNone(result['time_to_empty_seconds'])
        reading.update(elapsed=0, boot_id='boot2')
        self.assertIsNone(model.update(reading)['percentage'])

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
        for n in range(13):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            model.update(reading)
        reading.update(boot_id='boot2', elapsed=20, timestamp=100240, voltage_uv=3500000)
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

    def test_seed_ignores_boot_load_and_single_later_spike(self):
        model = Model(PROFILES)
        reading = sample()
        normal = reading['voltage_uv']
        for n in range(13):
            reading.update(elapsed=n*15, timestamp=100000+n*15,
                           voltage_uv=3500000 if n < 4 or n == 9 else normal)
            result = model.update(reading)
            if n < 12:
                self.assertIsNone(result['percentage'])
        self.assertEqual(result['percentage'], 50)
        self.assertEqual(result['method'], 'filtered-voltage-seed')

    def test_exhausted_estimate_is_unknown_even_after_charging_and_restart(self):
        model = Model(PROFILES)
        reading = sample()
        for n in range(13):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            model.update(reading)
        model.state['soc'] = .01
        reading.update(elapsed=195, timestamp=100195)
        result = model.update(reading)
        self.assertIsNone(result['percentage'])
        self.assertIsNone(result['time_to_empty_seconds'])
        self.assertEqual(result['estimate_status'], 'reference-exhausted')
        model = Model(PROFILES, json.loads(json.dumps(model.state)))
        for n in range(14, 50):
            reading.update(elapsed=n*15, timestamp=100000+n*15,
                           current_ua=500000, usb_online=True)
            result = model.update(reading)
        self.assertIsNone(result['percentage'])
        self.assertIsNone(result['time_to_full_seconds_at_current_rate'])
        self.assertEqual(result['capacity_updates'], 0)

    def test_upgrade_preserves_capacity_but_hides_old_zero(self):
        reading = sample()
        state = dict(schema=1, profile='atl', capacity_mah=4200, full_references=2,
                     capacity_updates=1, soc=0, previous=dict(reading))
        model = Model(PROFILES, state)
        reading.update(elapsed=15, timestamp=100015)
        result = model.update(reading)
        self.assertIsNone(result['percentage'])
        self.assertEqual(result['capacity_mah_estimated'], 4200)
        self.assertEqual(result['full_references'], 2)
        self.assertEqual(result['capacity_updates'], 1)

    def test_partial_learning_needs_two_comparable_large_intervals(self):
        model = Model(PROFILES)
        reading = sample()
        reading['current_ua'] = -50000
        model.update(reading)
        for _ in range(2):
            model.state.update(learning_anchor=None, anchor_net_mah=None)
            model.rest_reference(85, reading)
            model.state['anchor_net_mah'] = -1800  # 40% of a 4500 mAh cell.
            model.rest_reference(45, reading)
        self.assertEqual(model.state['capacity_candidates'], 2)
        self.assertEqual(model.state['capacity_updates'], 1)
        self.assertAlmostEqual(model.state['capacity_mah'], 4815)
        self.assertEqual(model.state['full_references'], 0)
        model.rest_reference(45, reading)
        self.assertEqual(model.state['capacity_updates'], 1)

    def test_partial_learning_rejects_small_span_and_temperature_change(self):
        for span, temperature in [(10, 25), (40, 30)]:
            model = Model(PROFILES)
            reading = sample(); reading['current_ua'] = -50000
            model.update(reading)
            model.rest_reference(85, reading)
            model.state['anchor_net_mah'] = -1800
            reading['temp_c'] = temperature
            model.rest_reference(85-span, reading)
            self.assertEqual(model.state['capacity_updates'], 0)
            self.assertEqual(model.state.get('capacity_candidates', 0), 0)

    def test_gap_and_charging_invalidate_partial_interval(self):
        for changes in [dict(elapsed=60, timestamp=100060),
                        dict(elapsed=15, timestamp=100015, current_ua=500000)]:
            model = Model(PROFILES)
            reading = sample(); reading['current_ua'] = -50000
            model.update(reading)
            model.rest_reference(85, reading)
            reading.update(changes)
            model.update(reading)
            self.assertIsNone(model.state['learning_anchor'])
            self.assertIsNone(model.state['anchor_net_mah'])

    def test_real_full_recovers_exhausted_reference(self):
        reading = sample()
        model = Model(PROFILES)
        model.update(reading)
        model.state.update(soc=0, estimate_exhausted=True)
        model.state.pop('seed_started')
        model.state.pop('seed_samples')
        reading.update(usb_online=True, current_ua=0, charger_state=5, voltage_uv=4350000)
        for n in range(1, 21):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            result = model.update(reading)
        self.assertEqual(result['percentage'], 100)
        self.assertEqual(result['time_to_full_seconds_at_current_rate'], 0)
        self.assertEqual(result['full_references'], 1)

    def test_low_current_ramping_voltage_is_not_a_quiet_reference(self):
        reading = sample()
        model = Model(PROFILES)
        for n in range(100):
            reading.update(elapsed=n*15, timestamp=100000+n*15,
                           current_ua=-50000, voltage_uv=3800000+n*1000)
            result = model.update(reading)
        self.assertLess(model.state['rest_seconds'], 600)
        self.assertIsNone(model.state['learning_anchor'])
        self.assertEqual(result['capacity_updates'], 0)

    def test_seed_window_restarts_when_charger_changes(self):
        model = Model(PROFILES)
        reading = sample()
        for n in range(14):
            reading.update(elapsed=n*15, timestamp=100000+n*15)
            if n == 10:
                reading.update(usb_online=True, current_ua=500000)
            result = model.update(reading)
        self.assertIsNone(result['percentage'])
        self.assertEqual(model.state['seed_started'], 150)

    def test_invalid_data_never_becomes_zero_percent(self):
        for field, value in [('voltage_uv', 0), ('current_ua', float('nan')),
                             ('temp_c', 100), ('id_uv', 1)]:
            reading = sample(); reading[field] = value
            with self.assertRaises(ValueError):
                Model(PROFILES).update(reading)


if __name__ == '__main__':
    unittest.main()
