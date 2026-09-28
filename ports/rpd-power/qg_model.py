"""Read-only PMI632 QG data, scaled from Lenovo's pinned qg-reg.h/qg-defs.h.

FIFO entries contain averages; the accumulator contains signed sample sums.
No stale SDAM SOC, register writes, charge policy or inferred IRQ timestamps.
"""


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def decode_snapshot(text):
    regs = {}
    for line in text.splitlines():
        address, value = (int(x, 16) for x in line.split('='))
        if address in regs or not 0 <= value <= 255:
            raise ValueError('Duplicate QG register or invalid byte')
        regs[address] = value

    def number(address, size=2):
        return sum(regs[address+i] << (8*i) for i in range(size))

    def reference(address):
        v, i = number(address), number(address+2)
        if v == 0x8000 or i == 0x8000:
            return None
        voltage = v * 194637 // 1000
        current = -signed(i, 16) * 152588 / 1000
        if not 2800000 < voltage < 4500000 or abs(current) > 80000:
            return None
        return {'voltage_uv': voltage, 'current_ua': current, 'raw': [v, i]}

    config = number(0x4851)
    slots = ((regs[0x4851] >> 3) & 7) + 1
    count = 1 << ((regs[0x4851] & 7) + 1)
    interval_ms = regs[0x4852] * 10
    completed, accum_count = regs[0x480a] & 15, regs[0x488e]
    if (not regs[0x4808] & 0x80 or not regs[0x4808] & 1 or
            interval_ms == 0 or completed > slots or accum_count >= count or
            (completed == slots and accum_count)):
        raise ValueError('QG not ready or inconsistent sample counters')
    return {'config': config, 'slots': slots, 'samples_per_slot': count,
            'interval_ms': interval_ms, 'completed': completed, 'accum_count': accum_count,
            'accum_current_raw': signed(number(0x488b, 3), 24),
            'fifo_current_raw': [signed(number(0x48a0+2*i), 16) for i in range(slots)],
            'fifo_voltage_raw': [number(0x4890+2*i) for i in range(slots)],
            'pon': reference(0x4870),
            'rest': reference(0x4874) if regs[0x4809] & 2 else None}


def charge_delta(previous, current, elapsed):
    """Return net mAh (positive charging), or None if coverage is unproven.

    The kernel rejects snapshots whose counters change while reading. The
    software also checks cadence/configuration and at most one observable wrap.
    Reading the same window twice must never count the same charge twice.
    """
    if not previous or not current or previous['config'] != current['config']:
        return None
    q, p = current, previous
    count, slots, period = q['samples_per_slot'], q['slots'], q['interval_ms'] / 1000
    window = slots * count
    before = p['completed'] * count + p['accum_count']
    after = q['completed'] * count + q['accum_count']
    samples = (after - before) % window
    # Allow endpoint quantization and a small clock drift, not a percentage
    # large enough to hide tens of seconds of stopped sampling during sleep.
    if (not 0 < elapsed < window * period or not samples or
            abs(samples * period - elapsed) > 2 * period + .01 * elapsed):
        return None
    if after >= before:
        indices = range(p['completed'], q['completed'])
    else:
        indices = list(range(p['completed'], slots)) + list(range(q['completed']))
    raw = q['accum_current_raw'] - p['accum_current_raw']
    for i in indices:
        if (q['fifo_current_raw'][i] == -32768 or q['fifo_voltage_raw'][i] == 0x8000 or
                not 2800000 < q['fifo_voltage_raw'][i] * 194637 / 1000 < 4500000):
            return None
        raw += q['fifo_current_raw'][i] * count
    current_ua = -raw * 152588 / 1000 / samples
    if abs(current_ua) > 5000000:
        return None
    return -raw * 152588 / 1000 * period / 3600000


def sleep_voltage_reference(previous, current, elapsed, awake_elapsed):
    """A provisional loaded-voltage seed, never charge counted over a gap.

    Once a long sleep overwrites the FIFO, three completed blocks can still
    describe its tail. Skip the newest block and accumulator to exclude wake
    load. The caller must confirm that sampling continues before using this
    candidate. These conservative stability gates are not an OCV qualification.
    """
    if not previous or not current or previous['config'] != current['config']:
        return None
    q = current
    slots = q['slots']
    block = q['samples_per_slot'] * q['interval_ms'] / 1000
    if (slots < 4 or block <= 0 or not 0 <= awake_elapsed <= block or
            elapsed - awake_elapsed <= slots * block):
        return None
    indices = [(q['completed'] - 2 - i) % slots for i in range(3)]
    # Unchanged data cannot establish that the gauge ran while asleep.
    if all((q['fifo_voltage_raw'][i], q['fifo_current_raw'][i]) ==
           (previous['fifo_voltage_raw'][i], previous['fifo_current_raw'][i])
           for i in indices):
        return None
    voltages = [q['fifo_voltage_raw'][i] * 194637 // 1000 for i in indices]
    currents = [-q['fifo_current_raw'][i] * 152588 / 1000 for i in indices]
    if (not all(2800000 < v < 4500000 for v in voltages) or
            not all(-200000 <= i <= 0 for i in currents) or
            max(voltages) - min(voltages) > 10000 or
            max(currents) - min(currents) > 20000):
        return None
    return {'voltage_uv': sorted(voltages)[1],
            'current_ua': sum(currents) / len(currents)}
