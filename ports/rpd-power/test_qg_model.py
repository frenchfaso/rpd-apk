import copy
import unittest
from qg_model import charge_delta, decode_snapshot
from test_power_model import Model, PROFILES, sample


def frame(ticks, raw_current=2000):
    ticks %= 2048
    return dict(config=0x1e3f, slots=8, samples_per_slot=256, interval_ms=300,
                completed=ticks//256, accum_count=ticks%256,
                accum_current_raw=(ticks%256)*raw_current,
                fifo_current_raw=[raw_current]*8, fifo_voltage_raw=[20000]*8,
                pon=None, rest=None)


def raw_snapshot():
    r={a:0 for start,length in [(0x4808,3),(0x4851,2),(0x4870,8),(0x4888,7),
                               (0x4890,16),(0x48a0,16)] for a in range(start,start+length)}
    r.update({0x4808:0x81,0x4851:0x3f,0x4852:30,0x488e:10,0x488b:0x20,0x488c:0x4e,
              0x4870:0xc3,0x4871:0x4c,0x4872:0x7b,0x4875:0x80,0x4877:0x80})
    for i in range(8):
        r.update({0x4890+2*i:0x20,0x4891+2*i:0x4e,0x48a0+2*i:0xd0,0x48a1+2*i:7})
    return r


def decode(r):
    return decode_snapshot(''.join(f'{a:04x}={v:02x}\n' for a,v in r.items()))


class GaugeTests(unittest.TestCase):
    def test_units_and_low_load_power_on_reference(self):
        q=decode(raw_snapshot())
        self.assertEqual(q['samples_per_slot'],256)
        self.assertEqual(q['interval_ms'],300)
        self.assertEqual(q['accum_current_raw'],20000)
        self.assertEqual(q['pon']['voltage_uv'],3824811)
        self.assertAlmostEqual(q['pon']['current_ua'],-18768.324)
        self.assertIsNone(q['rest'])

    def test_signed_accumulator_and_fifo(self):
        r=raw_snapshot();r.update({0x488b:0xe0,0x488c:0xb1,0x488d:0xff,
                                  0x48a0:0x30,0x48a1:0xf8})
        q=decode(r)
        self.assertEqual(q['accum_current_raw'],-20000)
        self.assertEqual(q['fifo_current_raw'][0],-2000)

    def test_charge_in_same_block_crossing_block_and_ring_wrap(self):
        for start in (30,240,2030):
            for current in (2000,-2000):
                delta=charge_delta(frame(start,current),frame(start+50,current),15)
                self.assertAlmostEqual(delta,-current*.152588*15/3600,places=9)

    def test_variable_load_integrates_samples_not_endpoint_currents(self):
        p=frame(250,1000);q=frame(300,2000)
        q['fifo_current_raw'][0]=1100
        expected=-((1100*256-1000*250)+2000*44)*152.588*.3/3600000
        self.assertAlmostEqual(charge_delta(p,q,15),expected,places=9)

    def test_repeat_config_change_gap_and_bad_cadence_rejected(self):
        self.assertIsNone(charge_delta(frame(30),frame(30),15))
        self.assertIsNone(charge_delta(frame(30),frame(80),630))
        self.assertIsNone(charge_delta(frame(30),frame(31),15))
        q=frame(80);q['config']+=1
        self.assertIsNone(charge_delta(frame(30),q,15))

    def test_reset_fifo_rejected_only_when_used(self):
        q=frame(300);q['fifo_voltage_raw'][0]=0x8000
        self.assertIsNone(charge_delta(frame(250),q,15))
        self.assertIsNotNone(charge_delta(frame(270),q,9))

    def test_not_ready_invalid_counters_and_reset_reference(self):
        r=raw_snapshot();r[0x4808]=1
        with self.assertRaises(ValueError): decode(r)
        r=raw_snapshot();r[0x480a]=9
        with self.assertRaises(ValueError): decode(r)
        r=raw_snapshot();r.update({0x4809:2,0x4871:0x80,0x4870:0})
        self.assertIsNone(decode(r)['pon'])
        self.assertIsNone(decode(r)['rest'])

    def test_model_prefers_hardware_charge_and_rejects_missing_window(self):
        model=Model(PROFILES);reading=sample()
        for n in range(14):
            reading.update(elapsed=n*15,timestamp=100000+n*15,qg=frame(n*50))
            result=model.update(reading)
        expected=50-305.176*15/3600*100/4850
        self.assertAlmostEqual(model.state['soc'],expected)
        self.assertEqual(result['integration_source'],'qg-fifo')
        self.assertEqual(result['hardware_intervals'],13)
        self.assertAlmostEqual(model.state['rate_ua'], -305176+(-485000+305176)*(300/315)**13)
        reading.update(elapsed=210,timestamp=100210,qg=None)
        result=model.update(reading)
        self.assertEqual(result['integration_source'],'instantaneous-samples')

    def test_new_rest_reference_used_once_not_stale_at_startup(self):
        model=Model(PROFILES);reading=sample();q=frame(0)
        ref=dict(voltage_uv=4000000,current_ua=-10000,raw=[20551,65])
        q['rest']=copy.deepcopy(ref);reading['qg']=q
        result=model.update(reading)
        self.assertEqual(result['hardware_references'],0)
        for n in range(1,14):
            q=frame(n*50);q['rest']=copy.deepcopy(ref)
            if n>=12: q['rest']['raw'][0]+=1;q['rest']['voltage_uv']+=195
            reading.update(elapsed=n*15,timestamp=100000+n*15,qg=q)
            result=model.update(reading)
        self.assertEqual(result['hardware_references'],1)
        self.assertEqual(result['reference_source'],'qg-rest')

    def test_power_on_requires_changed_data_new_boot_and_early_start(self):
        for changed,new_boot,age,accepted in [(True,True,30,True),(False,True,30,False),
                                             (True,False,400,False),(True,True,400,False)]:
            model=Model(PROFILES);reading=sample();q=frame(0)
            q['pon']=dict(voltage_uv=4000000,current_ua=-10000,raw=[20551,65])
            reading['qg']=q;model.update(reading)
            newer=copy.deepcopy(q)
            if changed: newer['pon']['raw'][0]+=1;newer['pon']['voltage_uv']+=195
            reading.update(timestamp=101000,elapsed=age,qg=newer,
                           boot_id='boot2' if new_boot else 'boot1')
            result=model.update(reading)
            self.assertEqual(result['hardware_references'],int(accepted))
            if accepted: self.assertEqual(result['reference_source'],'qg-power-on')


if __name__ == '__main__':
    unittest.main()
