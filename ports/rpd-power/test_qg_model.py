import copy
import json
import unittest
from qg_model import charge_delta, decode_snapshot, sleep_voltage_reference
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
    def ready_model(self, ticks=1000):
        model=Model(PROFILES);reading=sample()
        for n in range(13):
            reading.update(elapsed=n*15,awake_elapsed=n*15,timestamp=100000+n*15,
                           qg=frame(ticks-600+n*50))
            model.update(reading)
        return model,reading

    def test_sleep_charge_is_measured_across_blocks_wrap_and_restart(self):
        for seconds in (30,180,300,600):
            for raw in (2000,-2000):
                model,reading=self.ready_model()
                reading['qg']=frame(1000,raw)
                model.state['previous']=copy.deepcopy(reading)
                model.state.update(learning_anchor={'soc':85,'temp_c':25,'full':False,
                                                   'current_ua':-50000},anchor_net_mah=-100)
                before=model.state['soc']
                # The persisted snapshot must work across a monitor restart too.
                model=Model(PROFILES,json.loads(json.dumps(model.state)))
                reading.update(elapsed=180+seconds,awake_elapsed=181,timestamp=100180+seconds,
                               current_ua=-50000,qg=frame(1000+round(seconds/.3),raw))
                result=model.update(reading)
                delta=-raw*.152588*seconds/3600
                self.assertAlmostEqual(model.state['soc'],before+delta*100/4850)
                self.assertAlmostEqual(model.state['anchor_net_mah'],-100+delta)
                self.assertAlmostEqual(result['charge_delta_mah'],delta)
                self.assertEqual(result['integration_source'],'qg-fifo')
                self.assertIsNotNone(result['percentage'])
                self.assertEqual(model.state['rate_seconds'],0)
                self.assertIsNone(result['time_to_empty_seconds'])
                self.assertIsNone(result['time_to_full_seconds_at_current_rate'])

    def test_sleep_cannot_qualify_full_or_quiet_reference(self):
        for full in (False,True):
            model,reading=self.ready_model()
            model.state.update(full_seconds=285,rest_seconds=585)
            reading.update(elapsed=780,awake_elapsed=181,timestamp=100780,
                           current_ua=0,qg=frame(952),usb_online=full,
                           charger_state=5 if full else 7,
                           voltage_uv=4350000 if full else reading['voltage_uv'])
            result=model.update(reading)
            self.assertEqual(result['integration_source'],'qg-fifo')
            self.assertEqual(result['full_references'],0)
            self.assertEqual(model.state['full_seconds'],0)
            self.assertEqual(model.state['rest_seconds'],0)

    def test_missing_overwritten_stopped_or_reconfigured_fifo_is_not_integrated(self):
        for seconds,qg in [(630,frame(1052)),(300,None),(300,frame(1000)),
                           (300,{**frame(2000),'config':0})]:
            model,reading=self.ready_model()
            model.state.update(learning_anchor={'soc':85},anchor_net_mah=-100)
            reading.update(elapsed=180+seconds,awake_elapsed=181,timestamp=100180+seconds,qg=qg)
            result=model.update(reading)
            self.assertEqual(result['integration_source'],'none')
            self.assertIsNone(result['charge_delta_mah'])
            self.assertIsNone(result['percentage'])
            self.assertIsNone(model.state['learning_anchor'])

    def test_even_short_sleep_must_not_extrapolate_endpoint_current(self):
        model,reading=self.ready_model();before=model.state['soc']
        reading.update(elapsed=210,awake_elapsed=181,timestamp=100210,qg=None)
        result=model.update(reading)
        self.assertEqual(model.state['soc'],before)
        self.assertEqual(result['integration_source'],'none')
        self.assertEqual(model.state['rate_seconds'],0)

    def test_matching_fifo_in_a_different_boot_is_not_charge_evidence(self):
        model,reading=self.ready_model()
        reading.update(elapsed=480,awake_elapsed=480,timestamp=100480,
                       boot_id='boot2',qg=frame(2000))
        result=model.update(reading)
        self.assertEqual(result['integration_source'],'none')
        self.assertIsNone(result['percentage'])

    def test_seed_window_cannot_be_completed_by_sleep(self):
        model=Model(PROFILES);reading=sample(qg=frame(0))
        model.update(reading)
        reading.update(elapsed=300,timestamp=100300,qg=frame(1000))
        result=model.update(reading)
        self.assertEqual(result['integration_source'],'qg-fifo')
        self.assertEqual(result['estimate_status'],'collecting-reference')
        self.assertIsNone(result['percentage'])

    def test_long_interval_must_not_hide_a_partially_stopped_gauge(self):
        self.assertIsNone(charge_delta(frame(0),frame(1900),600))
        self.assertIsNone(charge_delta(frame(0),frame(1950),600))
        self.assertIsNotNone(charge_delta(frame(0),frame(2000),600.3))

    def test_overnight_sleep_tail_recovers_seed_without_learning_missing_charge(self):
        model,reading=self.ready_model()
        model.state.update(learning_anchor={'soc':85},anchor_net_mah=-100,
                           capacity_mah=4700,capacity_updates=2)
        # M10 2026-09-28: 9 h 26 min gap, about 140 mA at the sleep tail.
        q=frame(5*256+140)
        q.update(accum_current_raw=171365,
                 fifo_current_raw=[917,917,916,915,915,917,917,917],
                 fifo_voltage_raw=[19313,19312,19311,19309,19308,19316,19316,19315])
        reading.update(elapsed=34169.530854,awake_elapsed=195.019549,
                       timestamp=134169.530854,qg=q,voltage_uv=3721070,temp_c=23.6)
        first=model.update(reading)
        self.assertIsNone(first['percentage'])
        self.assertIsNone(first['charge_delta_mah'])
        self.assertEqual(first['integration_source'],'none')
        self.assertIsNone(model.state['learning_anchor'])
        # Persisted candidate survives a daemon restart; continuity is checked.
        model=Model(PROFILES,json.loads(json.dumps(model.state)))
        q=copy.deepcopy(q)
        q.update(accum_count=190,accum_current_raw=171365+50*1900)
        reading.update(elapsed=34184.530854,awake_elapsed=210.019549,
                       timestamp=134184.530854,qg=q)
        result=model.update(reading)
        self.assertEqual(result['method'],'sleep-voltage-seed')
        self.assertEqual(result['reference_source'],'qg-sleep-loaded-voltage')
        self.assertIsNotNone(result['percentage'])
        self.assertIsNone(result['time_to_empty_seconds'])
        self.assertAlmostEqual(result['charge_delta_mah'],-1900*.152588*15/3600)
        self.assertIsNone(model.state['learning_anchor'])
        self.assertIsNone(model.state['anchor_net_mah'])
        self.assertEqual(result['capacity_updates'],2)
        self.assertEqual(result['capacity_mah_estimated'],4700)

    def test_sleep_seed_requires_fresh_stable_low_load_discharge(self):
        p=frame(1000)
        q=frame(1400,900)
        self.assertIsNotNone(sleep_voltage_reference(p,q,34000,15))
        self.assertIsNone(sleep_voltage_reference(q,q,34000,15))
        self.assertIsNone(sleep_voltage_reference(p,q,600,15))
        self.assertIsNone(sleep_voltage_reference(p,q,34000,90))
        self.assertIsNone(sleep_voltage_reference(p,q,34000,-1))
        self.assertIsNone(sleep_voltage_reference(None,q,34000,15))
        for changes in [dict(config=0),dict(slots=3),
                        dict(fifo_current_raw=[-900]*8),
                        dict(fifo_current_raw=[2000]*8),
                        dict(fifo_voltage_raw=[0x8000]*8),
                        dict(fifo_current_raw=[900,900,900,1200,900,900,900,900]),
                        dict(fifo_voltage_raw=[20000,20000,20000,20100,20000,20000,20000,20000])]:
            self.assertIsNone(sleep_voltage_reference(p,{**q,**changes},34000,15))

    def test_sleep_seed_excludes_newest_completed_block_and_accumulator(self):
        p=frame(1000);q=frame(1400,900)
        q['fifo_current_raw'][4]=5000
        q['fifo_voltage_raw'][4]=19000
        q['accum_current_raw']=600000
        self.assertIsNotNone(sleep_voltage_reference(p,q,34000,15))
        # The same selection works over the ring boundary.
        q=frame(10,900);q['fifo_voltage_raw'][7]=19000
        self.assertIsNotNone(sleep_voltage_reference(p,q,34000,15))

    def test_sleep_candidate_is_dropped_on_unproven_followup(self):
        for changes in [dict(qg=None),dict(usb_online=True),dict(boot_id='other'),
                        dict(current_ua=100000),dict(temp_c=50)]:
            model,reading=self.ready_model()
            reading.update(elapsed=34180,awake_elapsed=195,timestamp=134180,qg=frame(1400,900))
            model.update(reading)
            self.assertIn('pending_sleep_reference',model.state)
            reading.update(elapsed=34195,awake_elapsed=210,timestamp=134195,qg=frame(1450,900))
            reading.update(changes)
            result=model.update(reading)
            self.assertNotEqual(result['reference_source'],'qg-sleep-loaded-voltage')
            self.assertNotIn('pending_sleep_reference',model.state)

    def test_sleep_reference_is_not_used_across_reboot_or_charging(self):
        for changes in [dict(boot_id='other'),dict(usb_online=True),dict(temp_c=5)]:
            model,reading=self.ready_model()
            reading.update(elapsed=34180,awake_elapsed=195,timestamp=134180,qg=frame(1400,900))
            reading.update(changes)
            model.update(reading)
            self.assertNotIn('pending_sleep_reference',model.state)

    def test_m10_s2idle_trace_with_clock_skew_and_fifo_wrap(self):
        # 2026-09-24, 180.655 s in s2idle within a 195.857 s poll interval.
        # QG clock and BOOTTIME differ by 0.943 s; no inferred sleep current.
        p=frame(7*256+114);q=frame(2*256+2)
        p.update(accum_current_raw=-134067,
                 fifo_current_raw=[-1461,-1412,-1365,-1322,-1286,-1242,-1205,-1510])
        q.update(accum_current_raw=0,
                 fifo_current_raw=[-1131,-442,-1365,-1322,-1286,-1242,-1205,-1166])
        self.assertAlmostEqual(charge_delta(p,q,195.85679653700208),7.211270733)

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
