"""Conservative userspace SOC estimate. Never controls hardware or shutdown.

OEM OCV curves provide a rough seed, not measured SOC. Charge counting refines
it between observations. Full-charge and rest references correct drift; capacity
learning requires substantial uninterrupted intervals between comparable references.
Low-current references and voltage seeds remain unvalidated approximations.
"""
import math
import statistics
from qg_model import charge_delta


def clamp(value, low, high):
    return max(low, min(high, value))


def interpolate(x, xs, ys):
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i] and xs[i] > xs[i-1]:
            return ys[i-1] + (ys[i]-ys[i-1]) * (x-xs[i-1]) / (xs[i]-xs[i-1])
    return ys[-1]


def curve_soc(profile, voltage_uv, temp_c, charging):
    curve = profile['charging' if charging else 'discharging']
    voltages = [interpolate(temp_c, curve['temperatures'], row) for row in curve['voltage_uv']]
    # OEM LWN -10 C curve contains a small 4.6 mV local inversion.
    # Use a monotone envelope for inversion; preserve the original data file.
    for i in range(1, len(voltages)):
        if voltages[i] > voltages[i-1] + 5000:
            raise ValueError('OCV curve inversion exceeds tolerated measurement noise')
        voltages[i] = min(voltages[i], voltages[i-1])
    return interpolate(voltage_uv, list(reversed(voltages)), list(reversed(curve['soc'])))


def select_profile(profiles, id_uv):
    if not 0 < id_uv < 1875000:
        raise ValueError('Invalid battery ID voltage')
    kohm = 100 * id_uv / (1875000 - id_uv)
    matches = [name for name, p in profiles.items() if abs(kohm / p['battery_id_kohm'] - 1) <= .15]
    if len(matches) != 1:
        raise ValueError('Unknown battery profile')
    return matches[0]


class Model:
    def __init__(self, profiles, state=None):
        self.profiles = profiles
        self.state = state or {}

    def update(self, sample):
        required = ('voltage_uv', 'current_ua', 'temp_c', 'elapsed', 'timestamp', 'id_uv')
        if not all(math.isfinite(sample[k]) for k in required):
            raise ValueError('Non-finite sample')
        if not (2800000 < sample['voltage_uv'] < 4500000 and
                abs(sample['current_ua']) <= 5000000 and -10 <= sample['temp_c'] <= 50):
            raise ValueError('Sample outside estimator range')
        name = select_profile(self.profiles, sample['id_uv'])
        profile = self.profiles[name]
        s = self.state
        if s.get('profile') != name or s.get('schema') != 1:
            s = self.state = {'schema': 1, 'profile': name, 'capacity_mah': profile['nominal_mah'],
                             'full_references': 0, 'capacity_updates': 0}
        s['capacity_mah'] = clamp(float(s['capacity_mah']), .5 * profile['nominal_mah'], 1.1 * profile['nominal_mah'])
        # Migrate without discarding learned capacity or diagnostic counters.
        if s.get('estimator_version') != 2:
            s.update(estimator_version=2, learning_anchor=None, anchor_net_mah=None,
                     pending_capacity=None)
            if 'soc' in s and s['soc'] <= .5:
                # Replace an already exhausted legacy seed once, using the new
                # delayed window. Keep capacity and history; this is not learning.
                s.update(seed_started=sample['elapsed'], seed_samples=[],
                         estimate_exhausted=False)
        p = s.get('previous')
        dt = sample['elapsed'] - p['elapsed'] if p else 0
        continuous = bool(p and sample['boot_id'] == p['boot_id'] and 0 < dt <= 45)
        reference = curve_soc(profile, sample['voltage_uv'], sample['temp_c'], sample['current_ua'] > 0)
        integration_source = 'none'
        interval_current = float(sample['current_ua'])
        if not continuous:
            # A brief reboot provides no new charge measurement. Preserve the
            # last estimate, without integrating unobserved current or using
            # boot-load terminal voltage as a new OCV reference.
            wall_gap = sample['timestamp'] - p['timestamp'] if p else -1
            last_soc = s.get('soc')
            resume = (p and 0 <= wall_gap <= 180 and
                      isinstance(last_soc, (int, float)) and math.isfinite(last_soc) and
                      0 <= last_soc <= 100)
            s.update(soc=clamp(last_soc if resume else reference, 0, 99),
                     method='last-estimate-after-gap' if resume else 'voltage-seed',
                     rest_seconds=0, full_seconds=0, anchor_net_mah=None, was_full=False,
                     learning_anchor=None, rest_reference_taken=False, pending_hardware_rest=None)
            if not resume:
                s.update(seed_started=sample['elapsed'], seed_samples=[],
                         estimate_exhausted=False)
            elif 'seed_started' in s:
                # A seed window must not span an unobserved interval.
                s.update(seed_started=sample['elapsed'], seed_samples=[])
        else:
            dq = charge_delta(p.get('qg'), sample.get('qg'), dt)
            integration_source = 'qg-fifo' if dq is not None else 'instantaneous-samples'
            if dq is None:
                dq = (sample['current_ua'] + p['current_ua']) / 2 * dt / 3600000
            else:
                s['hardware_intervals'] = s.get('hardware_intervals', 0) + 1
            interval_current = dq * 3600000 / dt
            s['soc'] = clamp(s['soc'] + dq * 100 / s['capacity_mah'], 0, 100)
            if s.get('anchor_net_mah') is not None:
                s['anchor_net_mah'] += dq
            s['method'] = 'current-integration'
        if 'seed_started' in s:
            if p and (sample['usb_online'] != p['usb_online'] or
                      (sample['current_ua'] > 20000 and p['current_ua'] < -20000) or
                      (sample['current_ua'] < -20000 and p['current_ua'] > 20000)):
                s.update(seed_started=sample['elapsed'], seed_samples=[])
            age = sample['elapsed'] - s['seed_started']
            if age >= 60:
                s['seed_samples'].append(reference)
            if age >= 180:
                s['soc'] = clamp(statistics.median(s['seed_samples']), 0, 99)
                s['method'] = 'filtered-voltage-seed'
                s['reference_source'] = 'loaded-voltage'
                del s['seed_started'], s['seed_samples']
            else:
                s['method'] = 'collecting-voltage-seed'
        qg, old_qg = sample.get('qg'), p.get('qg') if p else None
        hardware_reference = None
        hardware_source = None
        if qg and old_qg:
            # Untimestamped hardware references need evidence of freshness.
            # PON is only considered early in a *different* boot, with changed
            # raw data. Never reuse a previous boot's PON during a service restart.
            pon, old_pon = qg.get('pon'), old_qg.get('pon')
            if (not continuous and not resume and sample['elapsed'] <= 180 and
                    sample['boot_id'] != p['boot_id'] and pon and old_pon and
                    pon['raw'] != old_pon['raw']):
                hardware_reference = pon
                hardware_source = 'qg-power-on'
            rest, old_rest = qg.get('rest'), old_qg.get('rest')
            if continuous and rest:
                pending = s.get('pending_hardware_rest')
                if not old_rest or rest['raw'] != old_rest['raw']:
                    s['pending_hardware_rest'] = rest['raw']
                elif pending == rest['raw']:
                    hardware_reference = rest
                    hardware_source = 'qg-rest'
                    s['pending_hardware_rest'] = None
            else:
                s['pending_hardware_rest'] = None
        if hardware_reference and 10 <= sample['temp_c'] <= 45:
            s['reference_source'] = hardware_source
            reference = curve_soc(profile, hardware_reference['voltage_uv'], sample['temp_c'], False)
            s.update(soc=min(reference, 99.), estimate_exhausted=False,
                     method='hardware-voltage-reference')
            s['hardware_references'] = s.get('hardware_references', 0) + 1
            s.pop('seed_started', None)
            s.pop('seed_samples', None)
            if s['reference_source'] == 'qg-rest':
                self.rest_reference(reference, {**sample, 'current_ua': hardware_reference['current_ua']})
        if sample['current_ua'] > 100000:
            s.update(learning_anchor=None, anchor_net_mah=None)
        full = (sample['usb_online'] and sample['charger_state'] == 5 and
                -20000 <= sample['current_ua'] <= 100000 and 10 <= sample['temp_c'] <= 45 and
                sample['voltage_uv'] >= sample['float_voltage_uv'] - 50000)
        s['full_seconds'] = s.get('full_seconds', 0) + (dt if continuous else 0) if full else 0
        if s['full_seconds'] >= 300:
            if not s.get('was_full'):
                s['full_references'] += 1
            s.update(soc=100., method='full-charge-reference', anchor_net_mah=0., was_full=True,
                     estimate_exhausted=False, reference_source='charger-termination',
                     learning_anchor={'soc': 100., 'temp_c': sample['temp_c'], 'full': True})
            s.pop('seed_started', None)
            s.pop('seed_samples', None)
        elif not full:
            s['was_full'] = False
        # Do not advertise 100% from integration or a terminal-voltage seed alone.
        if not s.get('was_full'):
            s['soc'] = min(s['soc'], 99.)
        resting = (not sample['usb_online'] and abs(sample['current_ua']) <= 80000 and
                   continuous and abs(sample['voltage_uv'] - p['voltage_uv']) <= 5000)
        origin = s.get('rest_origin', sample)
        resting = (resting and 10 <= sample['temp_c'] <= 45 and
                   abs(sample['voltage_uv'] - origin['voltage_uv']) <= 5000 and
                   abs(sample['temp_c'] - origin['temp_c']) <= 2)
        if not resting or not s.get('rest_seconds'):
            s['rest_origin'] = dict(sample)
        s['rest_seconds'] = s.get('rest_seconds', 0) + (dt if continuous else 0) if resting else 0
        if not resting:
            s['rest_reference_taken'] = False
        if s['rest_seconds'] >= 600:
            if s.get('estimate_exhausted'):
                s['soc'] = min(reference, 99.)
                s['estimate_exhausted'] = False
            else:
                s['soc'] += clamp((reference - s['soc']) * .02, -.1, .1)
            s['method'] = 'rest-corrected'
            s['reference_source'] = 'low-current-voltage'
            if not s.get('rest_reference_taken'):
                self.rest_reference(reference, sample)
                s['rest_reference_taken'] = True
        # Zero from integration is not a measured empty battery. Latch the loss
        # of reference: charging alone cannot repair the unknown starting SOC.
        if 'seed_started' not in s and s['soc'] <= .5:
            s['estimate_exhausted'] = True
        available = 'seed_started' not in s and not s.get('estimate_exhausted')
        mode = 'charge' if sample['current_ua'] > 20000 else 'discharge' if sample['current_ua'] < -20000 else 'idle'
        if not continuous or mode != s.get('rate_mode'):
            s.update(rate_ua=float(sample['current_ua']), rate_seconds=0, rate_mode=mode)
        else:
            alpha = dt / (300 + dt)
            s['rate_ua'] += alpha * (interval_current - s['rate_ua'])
            s['rate_seconds'] += dt
        time_empty = time_full = None
        if available and s['rate_seconds'] >= 180:
            rate_ma = abs(s['rate_ua']) / 1000
            if rate_ma >= 50 and mode == 'discharge':
                time_empty = round(s['capacity_mah'] * s['soc'] / 100 / rate_ma * 3600)
            elif rate_ma >= 50 and mode == 'charge':
                # Extrapolation at the recent rate; final taper can take longer.
                time_full = round(s['capacity_mah'] * (100-s['soc']) / 100 / rate_ma * 3600)
        if s.get('was_full'):
            time_full = 0
        s['previous'] = dict(sample)
        return {**sample, 'profile': name, 'percentage': round(s['soc']) if available else None, 'estimated': True,
                'estimate_status': 'provisional' if available else
                    'collecting-reference' if 'seed_started' in s else 'reference-exhausted',
                'learning_status': 'waiting-for-quiet-reference' if s.get('learning_anchor') else
                    'waiting-for-first-reference',
                'capacity_candidates': s.get('capacity_candidates', 0),
                'integration_source': integration_source,
                'interval_current_ua': round(interval_current) if continuous else None,
                'hardware_intervals': s.get('hardware_intervals', 0),
                'reference_source': s.get('reference_source', 'legacy-voltage'),
                'hardware_references': s.get('hardware_references', 0),
                'time_to_empty_seconds': time_empty, 'time_to_full_seconds_at_current_rate': time_full,
                'method': s['method'], 'capacity_mah_estimated': round(s['capacity_mah']),
                'full_references': s['full_references'], 'capacity_updates': s['capacity_updates'],
                'uncertainty': 'unvalidated; terminal voltage is affected by load and ageing'}

    def rest_reference(self, reference, sample):
        """Consider one low-current endpoint per quiet period, not every sample.

        These are heuristic gates, not a validated error bound. Require two
        consistent independent intervals before changing capacity. Full-to-rest
        and partial rest-to-rest discharge use the same measured-charge test.
        """
        s = self.state
        anchor = s.get('learning_anchor')
        used = -(s.get('anchor_net_mah') or 0)
        if anchor:
            span = anchor['soc'] - reference
            comparable = (abs(sample['temp_c'] - anchor['temp_c']) <= 3 and
                          (anchor['full'] or
                           abs(sample['current_ua'] - anchor['current_ua']) <= 20000))
            if comparable and 10 <= reference <= 65 and span >= 35 and used >= 1000:
                candidate = used * 100 / span
                nominal = self.profiles[s['profile']]['nominal_mah']
                if .5 * nominal <= candidate <= 1.1 * nominal:
                    s['capacity_candidates'] = s.get('capacity_candidates', 0) + 1
                    pending = s.get('pending_capacity')
                    if pending and abs(candidate / pending - 1) <= .1:
                        s['capacity_mah'] = .9 * s['capacity_mah'] + .1 * (candidate + pending) / 2
                        s['capacity_updates'] += 1
                        s['pending_capacity'] = None
                    else:
                        s['pending_capacity'] = candidate
                # Consume the interval even if its candidate is implausible.
                anchor = None
            elif not comparable:
                anchor = None
        if anchor is None:
            s.update(learning_anchor=None, anchor_net_mah=None)
        if anchor is None and 10 <= reference <= 95:
            s['learning_anchor'] = {'soc': reference, 'temp_c': sample['temp_c'],
                                    'current_ua': sample['current_ua'], 'full': False}
            s['anchor_net_mah'] = 0.
