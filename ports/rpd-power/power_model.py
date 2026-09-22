"""Conservative userspace SOC estimate. Never controls hardware or shutdown.

OEM OCV curves provide a rough seed, not measured SOC. Charge counting refines
it between observations. Full-charge and rest references correct drift; capacity
learning requires a substantial, uninterrupted full-to-rest discharge interval.
"""
import math


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
        p = s.get('previous')
        dt = sample['elapsed'] - p['elapsed'] if p else 0
        continuous = bool(p and sample['boot_id'] == p['boot_id'] and 0 < dt <= 45)
        reference = curve_soc(profile, sample['voltage_uv'], sample['temp_c'], sample['current_ua'] > 0)
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
                     rest_seconds=0, full_seconds=0, anchor_net_mah=None, was_full=False)
        else:
            dq = (sample['current_ua'] + p['current_ua']) / 2 * dt / 3600000
            s['soc'] = clamp(s['soc'] + dq * 100 / s['capacity_mah'], 0, 100)
            if s.get('anchor_net_mah') is not None:
                s['anchor_net_mah'] += dq
            s['method'] = 'current-integration'
        full = (sample['usb_online'] and sample['charger_state'] == 5 and
                -20000 <= sample['current_ua'] <= 100000 and 10 <= sample['temp_c'] <= 45 and
                sample['voltage_uv'] >= sample['float_voltage_uv'] - 50000)
        s['full_seconds'] = s.get('full_seconds', 0) + (dt if continuous else 0) if full else 0
        if s['full_seconds'] >= 300:
            if not s.get('was_full'):
                s['full_references'] += 1
            s.update(soc=100., method='full-charge-reference', anchor_net_mah=0., was_full=True)
        elif not full:
            s['was_full'] = False
        # Do not advertise 100% from integration or a terminal-voltage seed alone.
        if not s.get('was_full'):
            s['soc'] = min(s['soc'], 99.)
        resting = (not sample['usb_online'] and abs(sample['current_ua']) <= 80000 and
                   continuous and abs(sample['voltage_uv'] - p['voltage_uv']) <= 5000)
        s['rest_seconds'] = s.get('rest_seconds', 0) + (dt if continuous else 0) if resting else 0
        if s['rest_seconds'] >= 600:
            s['soc'] += clamp((reference - s['soc']) * .02, -.1, .1)
            s['method'] = 'rest-corrected'
            used = -(s.get('anchor_net_mah') or 0)
            if 10 <= reference <= 65 and used >= 1000:
                candidate = used * 100 / (100 - reference)
                nominal = profile['nominal_mah']
                if .5 * nominal <= candidate <= 1.1 * nominal:
                    s['capacity_mah'] = .8 * s['capacity_mah'] + .2 * candidate
                    s['capacity_updates'] += 1
                    s['anchor_net_mah'] = None  # One update per independent interval.
        mode = 'charge' if sample['current_ua'] > 20000 else 'discharge' if sample['current_ua'] < -20000 else 'idle'
        if not continuous or mode != s.get('rate_mode'):
            s.update(rate_ua=float(sample['current_ua']), rate_seconds=0, rate_mode=mode)
        else:
            alpha = dt / (300 + dt)
            s['rate_ua'] += alpha * (sample['current_ua'] - s['rate_ua'])
            s['rate_seconds'] += dt
        time_empty = time_full = None
        if s['rate_seconds'] >= 180:
            rate_ma = abs(s['rate_ua']) / 1000
            if rate_ma >= 50 and mode == 'discharge':
                time_empty = round(s['capacity_mah'] * s['soc'] / 100 / rate_ma * 3600)
            elif rate_ma >= 50 and mode == 'charge':
                # Extrapolation at the recent rate; final taper can take longer.
                time_full = round(s['capacity_mah'] * (100-s['soc']) / 100 / rate_ma * 3600)
        if s.get('was_full'):
            time_full = 0
        s['previous'] = dict(sample)
        return {**sample, 'profile': name, 'percentage': round(s['soc']), 'estimated': True,
                'time_to_empty_seconds': time_empty, 'time_to_full_seconds_at_current_rate': time_full,
                'method': s['method'], 'capacity_mah_estimated': round(s['capacity_mah']),
                'full_references': s['full_references'], 'capacity_updates': s['capacity_updates'],
                'uncertainty': 'unvalidated; terminal voltage is affected by load and ageing'}
