import contextlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import bc_controlled_capacity_ops_v3 as m


def write(p,value):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))

class CapacityV3Tests(unittest.TestCase):
    def test_arithmetic_counts_adopted_pilot_inside16(self):
        self.assertEqual(m.capacity(0,64+10,32,16),128)
        self.assertEqual(m.capacity(0,64+11,32,16),129)
        self.assertEqual(m.capacity(0,64,32,16),118)
        self.assertEqual(m.capacity(0,80,16,16),118)

    def marker(self,binding):
        return {'version':'controlled-bounded-ops16-capacity-v1','ready':True,'controlled_native_slots':16,'judge_reserve':6,'global_cap':128,'global_reserved_total':128,**binding}

    def test_controlled_reservation_never_frees_while_alive_or_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);marker=root/'marker.json';binding={'controlled_plan_sha256':'plan','dispatcher_source_sha256':'source'}
            with patch.object(m,'CONTROLLED_ROOT',root),patch.object(m,'CONTROLLED_MARKER',marker):
                self.assertEqual(m.controlled_capacity(binding)['upper'],1)
                write(marker,self.marker(binding));self.assertEqual(m.controlled_capacity(binding)['upper'],16)
                write(root/'ops16-v1/status.json',{'state':'waiting_capacity_marker'})
                self.assertEqual(m.controlled_capacity(binding)['upper'],16)
                status={'capacity_marker_sha256':m.base.sha(marker),'all_eligible_resolved':True,'no_active_native':True,'unknown_reserved_slots':0,'running_native':0,'occupied_slots':0,'eligible_arms':120,'pending_eligible':0,'terminal_eligible':120,'pid':2147483000,'identity':'known'}
                write(root/'ops16-v1/status.json',status)
                with patch.object(m,'process_identity',return_value='known'):self.assertEqual(m.controlled_capacity(binding)['upper'],16)
                with patch.object(m,'process_identity',return_value=None):self.assertEqual(m.controlled_capacity(binding)['upper'],0)
                for key,value in [('unknown_reserved_slots',1),('occupied_slots',1),('terminal_eligible',119),('all_eligible_resolved',False),('no_active_native',False)]:
                    write(root/'ops16-v1/status.json',{**status,key:value})
                    with patch.object(m,'process_identity',return_value=None):self.assertEqual(m.controlled_capacity(binding)['upper'],16)

    def test_marker_tampering_blocks(self):
        binding={'controlled_plan_sha256':'plan','dispatcher_source_sha256':'source'}
        for key,value in [('ready',False),('controlled_native_slots',17),('judge_reserve',5),('global_reserved_total',129),('dispatcher_source_sha256','wrong')]:
            with self.subTest(key=key),self.assertRaises(ValueError):m.marker_valid({**self.marker(binding),key:value},binding)

    @contextlib.contextmanager
    def fixture(self,root,draining=10):
        bc=root/'bc';rq=root/'rq';mm=root/'mm';area=root/'ops';ctl=root/'controlled'
        bcjobs=[{'harness':h,'job_id':h+'/visual/q'} for h in ('hermes','dsh')]
        rqjobs=[{'scale_key':k,'job_id':'hermes/'+k+'/q'} for k in m.base.rqcloud.SCALE_KEYS]
        bcplan={'jobs':bcjobs};rqplan={'jobs':rqjobs};write(bc/'plan.json',bcplan);write(rq/'plan.json',rqplan);write(mm/'plan.json',{'jobs':[{'job_id':'mm'}]});write(mm/'campaign-manifest.json',{'plan_sha256':m.base.sha(mm/'plan.json')})
        for h in ('hermes','dsh'):write(bc/'markers'/h,{'plan_sha256':m.base.sha(bc/'plan.json')})
        bounds={k:(0 if k in ('scale_0800','scale_1000') else draining if k=='scale_0700' else 16) for k in m.base.rqcloud.SCALE_KEYS}
        with contextlib.ExitStack() as stack:
            for obj,key,val in [(m.base,'BC_ROOT',bc),(m.base,'RQ_ROOT',rq),(m.base,'MM_ROOT',mm),(m,'CONTROLLED_ROOT',ctl),(m,'CONTROLLED_MARKER',area/'markers/controlled16.json'),(m,'RESTORE',area/'restored')]:stack.enter_context(patch.object(obj,key,val))
            stack.enter_context(patch.object(m,'legacy_restore_absent'))
            stack.enter_context(patch.object(m,'controlled_binding',return_value={'controlled_plan_sha256':'plan','dispatcher_source_sha256':'source'}))
            stack.enter_context(patch.object(m.base,'load_validate',return_value=(bcplan,None)))
            stack.enter_context(patch.object(m.base.rqcloud,'load_validate',return_value=(rqplan,None)))
            stack.enter_context(patch.object(m.base.bccloud,'launch_marker',side_effect=lambda h:bc/'markers'/h))
            stack.enter_context(patch.object(m.base,'remaining_count',return_value=0))
            stack.enter_context(patch.object(m.base,'complete',return_value=False))
            stack.enter_context(patch.object(m.drain,'scale_bound',side_effect=lambda r,p,k:bounds[k]))
            yield bounds

    def test_marker_waits_until_drain_bound_at_most10(self):
        for draining,exists,upper in [(16,False,119),(11,False,114),(10,True,128),(0,True,118)]:
            with self.subTest(draining=draining),tempfile.TemporaryDirectory() as d:
                with self.fixture(Path(d),draining),patch.object(m.base.rqmon,'query_app',side_effect=AssertionError('No cloud action expected')):
                    row=m.cycle(True);self.assertEqual(m.CONTROLLED_MARKER.exists(),exists);self.assertEqual(row['global_reserved_total'],upper)
                    if exists:self.assertEqual(m.base.read(m.CONTROLLED_MARKER)['controlled_native_slots'],16)

    def test_unknown_or_wrong_plan_does_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            with self.fixture(Path(d),0):
                write(m.base.bccloud.launch_marker('dsh'),{'plan_sha256':'changed'})
                with self.assertRaises(ValueError):m.cycle(True)
                self.assertFalse(m.CONTROLLED_MARKER.exists())

    def test_restoring_0700_replaces_drain_bound_not_double_add(self):
        # .7 can return when one BC cell ends: 4RQ*16 + .7*16 +BC16+controlled16+judge6=118.
        self.assertEqual(m.capacity(0,64-0+16,16,16),118)
        # All7RQ while controlled16 runs would exceed cap even after BC ends.
        self.assertEqual(m.capacity(0,7*16,0,16),134)

    def test_dry_restore_accounts_cumulative_release_and_holds_seventh_scale(self):
        with tempfile.TemporaryDirectory() as d:
            with self.fixture(Path(d),0):
                binding={'controlled_plan_sha256':'plan','dispatcher_source_sha256':'source'}
                write(m.CONTROLLED_MARKER,self.marker(binding))
                def complete(root,jobs): return root==m.base.BC_ROOT
                with patch.object(m.base,'complete',side_effect=complete),patch.object(m.base.rqmon,'query_app',return_value={'state':'SUSPENDED','uid':'old'}),patch.object(m.base.rqmon,'assess_local',return_value={'eligible':True}):
                    row=m.cycle(False)
                states={r['scale_key']:r['state'] for r in row['restored']}
                self.assertEqual(states['scale_0700'],'would_restore_in_new_cci')
                self.assertEqual(states['scale_0800'],'would_restore_in_new_cci')
                self.assertEqual(states['scale_1000'],'restore_capacity_hold')
                self.assertEqual(row['global_reserved_total'],118)

    def test_0700_can_return_after_one_bc_cell_finishes(self):
        with tempfile.TemporaryDirectory() as d:
            with self.fixture(Path(d),0):
                binding={'controlled_plan_sha256':'plan','dispatcher_source_sha256':'source'}
                write(m.CONTROLLED_MARKER,self.marker(binding))
                def complete(root,jobs): return root==m.base.BC_ROOT and len(jobs)==1 and jobs[0]['harness']=='hermes'
                with patch.object(m.base,'complete',side_effect=complete),patch.object(m.base.rqmon,'query_app',return_value={'state':'SUSPENDED','uid':'old'}),patch.object(m.base.rqmon,'assess_local',return_value={'eligible':True}):
                    row=m.cycle(False)
                self.assertEqual(row['restored'][0]['state'],'would_restore_in_new_cci')
                self.assertTrue(all(r['state']=='held_until_both_bc_cells_complete' for r in row['restored'][1:]))
                self.assertEqual(row['global_reserved_total'],118)

    def test_three_distinct_new_cloud_names(self):
        self.assertEqual(len({m.restore_name(k) for k in m.HELD}),3)
        with self.assertRaises(ValueError):m.restore_name('scale_0250')

if __name__=='__main__':unittest.main()
