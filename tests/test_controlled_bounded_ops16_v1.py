import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_controlled_bounded_ops16_v1 as ops
from prepare_controlled_bounded_v1 import MODEL,ENCODING
from run_controlled_bounded_v1 import PROTOCOL

class Ops16Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.plan={'jobs':[]}
        for i in range(20):
            key=f'bc/q_{i:03d}';out=self.root/'jobs'/key/'visual';out.mkdir(parents=True)
            (out/'spec.json').write_text(json.dumps({'bounded_transport_encoding':ENCODING}))
            self.plan['jobs'].append({'job_id':key+'/visual','prefix_key':key,'method':'visual','eligible':True,'out':str(out),'spec_path':str(out/'spec.json')})
    def test_requested_capacity_is_16(self):
        info=ops.inspect(self.plan,self.root)
        self.assertEqual(len(ops.ready_jobs(self.plan,info)),16)
    def test_inherited_live_worker_consumes_slot(self):
        first=self.plan['jobs'][0];(Path(first['out'])/'supervisor.json').write_text('{"pid":123,"identity":"live"}')
        with patch('run_controlled_bounded_v1.process_identity',return_value='live'):
            info=ops.inspect(self.plan,self.root)
        self.assertEqual(info['running_native'],1);self.assertEqual(len(ops.ready_jobs(self.plan,info)),15)
    def test_unknown_dispatch_reserves_slot_and_is_not_selected(self):
        first=self.plan['jobs'][0];(Path(first['out'])/'dispatch.json').write_text('{}')
        info=ops.inspect(self.plan,self.root);self.assertEqual(info['unknown_reserved_slots'],1)
        chosen=ops.ready_jobs(self.plan,info);self.assertEqual(len(chosen),15);self.assertNotIn(first,chosen)
    def test_prior_known_completed_is_skipped(self):
        first=self.plan['jobs'][0];(Path(first['out'])/'trial-status.json').write_text('{"status":"completed","worker_reaped":true}')
        info=ops.inspect(self.plan,self.root);self.assertEqual(info['terminal_eligible'],1);self.assertNotIn(first,ops.ready_jobs(self.plan,info))
    def test_summary_waits_for_new_visual_reference(self):
        visual=self.plan['jobs'][0];out=Path(visual['out']).parent/'summary';out.mkdir();spec=out/'spec.json';spec.write_text(json.dumps({'bounded_transport_encoding':ENCODING}))
        summary=dict(visual,job_id=visual['prefix_key']+'/summary',method='summary',out=str(out),spec_path=str(spec));self.plan['jobs'].insert(0,summary)
        info=ops.inspect(self.plan,self.root);self.assertEqual(info['states'][summary['job_id']],'waiting_visual')
        (Path(visual['out'])/'trial-status.json').write_text('{"status":"failed","worker_reaped":true}')
        control={'method':'visual','passed':True,'first_actual_prompt_tokens':5328,'native_identity_verified':True,'native_hashes':['native'],
            'actual_route':MODEL,'bounded_native_protocol':PROTOCOL,'bounded_transport_encoding':ENCODING}
        (Path(visual['out'])/'compression-control.json').write_text(json.dumps(control))
        self.assertEqual(ops.inspect(self.plan,self.root)['states'][summary['job_id']],'ready')
    def test_no_future_local_bc_reservation_admits_16_at_59_visible(self):
        # Two visible processes per new trial, plus reserved growth to four.
        snapshot={i:{'identity':str(i),'ppid':0,'argv':['fixture']} for i in range(1,60)}
        reservations=[]
        with patch.object(ops.admission,'CORE_WORKERS',2):
            ops.configure_local_admission()
            for index in range(16):
                ok,report,_=ops.admission.capacity(snapshot,reservations,4)
                self.assertTrue(ok,(index,report));self.assertEqual(report['core_reserved_growth'],0)
                pid=1000+index*10
                snapshot[pid]={'identity':str(pid),'ppid':0,'argv':['python','fixture-supervisor']}
                snapshot[pid+1]={'identity':str(pid+1),'ppid':pid,'argv':['python','fixture-native']}
                reservations.append({'pid':pid,'identity':str(pid),'process_cost':4,'owner':ops.VERSION,'job_id':str(index)})
            self.assertEqual(report['projected'],127)
            self.assertFalse(ops.admission.capacity(snapshot,reservations,4)[0])
    def test_actual_existing_local_bc_growth_is_still_reserved(self):
        snapshot={100:{'identity':'core','ppid':0,'argv':['python',str(ops.ROOT/'scripts/run_bc_trial_v3.py'),
            '--out',str(ops.ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3/jobs/existing')]},
            101:{'identity':'native','ppid':100,'argv':['python','native']}}
        with patch.object(ops.admission,'CORE_WORKERS',2):
            ops.configure_local_admission();ok,report,_=ops.admission.capacity(snapshot,[],4)
        self.assertTrue(ok);self.assertEqual(report['core_reserved_growth'],3)
        self.assertEqual(report['limit'],127)
    def test_marker_rejects_over128_and_wrong_source(self):
        (self.root/'plan.json').write_text('{}');p=self.root/'marker.json'
        marker={'version':ops.MARKER_VERSION,'ready':True,'controlled_native_slots':16,'global_cap':128,'judge_reserve':6,'global_reserved_total':128,
            'controlled_plan_sha256':ops.sha(self.root/'plan.json'),'dispatcher_source_sha256':ops.sha(ops.__file__),
            'coordinator_stops':[{'pid':pid,'identity':v[0]} for pid,v in ops.ALLOWED_STOPS.items()]}
        p.write_text(json.dumps(marker));ops.validate_marker(p,self.root)
        marker['global_reserved_total']=129;p.write_text(json.dumps(marker))
        with self.assertRaises(ValueError):ops.validate_marker(p,self.root)
        marker['global_reserved_total']=128;marker['dispatcher_source_sha256']='wrong';p.write_text(json.dumps(marker))
        with self.assertRaises(ValueError):ops.validate_marker(p,self.root)
    def test_pid_identity_reuse_never_signalled(self):
        with patch.object(ops,'process_record',return_value={'pid':558793,'identity':'wrong','argv':[]}),patch.object(ops,'pidfd_signal') as sig:
            with self.assertRaises(ValueError):ops.verify_coordinator(558793,ops.ALLOWED_STOPS[558793][0],self.root)
            sig.assert_not_called()
    def admission_mocks(self):
        return [patch.object(ops.admission,'STATE',self.root/'admission'),patch.object(ops.admission,'processes',return_value={}),
            patch.object(ops.admission,'capacity',return_value=(True,{},[])),patch.object(ops.admission,'memory_capacity',return_value=(True,{}))]
    def test_post_intent_spawn_failure_stays_unknown_no_replay(self):
        patches=self.admission_mocks()
        for p in patches:p.start();self.addCleanup(p.stop)
        job=self.plan['jobs'][0]
        with patch.object(ops.subprocess,'Popen',side_effect=RuntimeError('uncertain spawn')) as spawn:
            with self.assertRaises(RuntimeError):ops.spawn_one(job,['fixture'])
            with self.assertRaises(ValueError):ops.spawn_one(job,['fixture'])
            self.assertEqual(spawn.call_count,1)
        self.assertEqual(ops.inspect(self.plan,self.root)['unknown_reserved_slots'],1)
    def test_known_admission_denial_creates_no_dispatch_or_paid_child(self):
        patches=self.admission_mocks()
        for p in patches:p.start();self.addCleanup(p.stop)
        job=self.plan['jobs'][0]
        with patch.object(ops.admission,'capacity',return_value=(False,{},[])),patch.object(ops.subprocess,'Popen') as spawn:
            child,report=ops.spawn_one(job,['fixture']);self.assertIsNone(child);spawn.assert_not_called()
        self.assertFalse((Path(job['out'])/'dispatch.json').exists())

if __name__=='__main__':unittest.main()
