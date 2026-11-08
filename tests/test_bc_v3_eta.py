from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import estimate_bc_v3_eta as eta


class MetadataEtaTests(unittest.TestCase):
    def test_throughput_separates_completed_failures_and_windows(self):
        rows=[{'finished':990,'status':'completed'},{'finished':800,'status':'timeout'},
              {'finished':200,'status':'failed'},{'finished':None,'status':'completed'}]
        ten=eta.window(rows,1000,600);twenty=eta.window(rows,1000,1200)
        self.assertEqual(ten['all_terminal_count'],2);self.assertEqual(ten['completed_only_count'],1)
        self.assertEqual(ten['all_terminal_per_hour'],12);self.assertEqual(twenty['all_terminal_count'],3)
        self.assertEqual(twenty['completed_only_count'],1)

    def test_complete_duration_missing_is_not_filled_from_timeout_cap(self):
        stats=eta.durations([{'seconds':100},{'seconds':300},{'seconds':None}])
        self.assertEqual(stats['mean_seconds'],200);self.assertEqual(stats['missing_count'],1)

    def cell(self):
        return {'planned':300,'states':{'terminal':30,'active':30,'pending':240},'timeout_seconds':1800,
                'throughput':{'10m':{'all_terminal_count':10,'all_terminal_per_hour':60},
                              '20m':{'all_terminal_count':10,'all_terminal_per_hour':30}}}

    def test_eta_is_gated_and_unknown_claims_do_not_get_invented_end_times(self):
        cell=self.cell();self.assertFalse(eta.eta_projection({'a':cell},['cloud still starting'],1000)['available'])
        cell['states']['unknown']=1
        result=eta.eta_projection({'a':cell},[],1000)
        self.assertFalse(result['available']);self.assertIn('unknown',result['reasons'][0])

    def test_slowest_cell_and_both_timezones_not_aggregate_throughput(self):
        fast=self.cell();slow=self.cell();slow['throughput']={'10m':{'all_terminal_count':5,'all_terminal_per_hour':30},
                                                          '20m':{'all_terminal_count':5,'all_terminal_per_hour':15}}
        result=eta.eta_projection({'fast':fast,'slow':slow},[],1000)
        self.assertEqual(result['remaining_seconds_range'],[32400,66600])
        self.assertTrue(result['utc_range'][0].endswith('+00:00'));self.assertTrue(result['beijing_range'][0].endswith('+08:00'))
        self.assertEqual(eta.instant(result['utc_range'][0]),eta.instant(result['beijing_range'][0]))

    def test_metadata_classification_does_not_require_native_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            job=Path(temporary);(job/'claim').mkdir();(job/'claim/owner.json').write_text(json.dumps({'hostname':'cloud','boot_id':'b','claimed_at':eta.stamp(100)}))
            local={'hostname':'local','boot_id':'a','pid_namespace':'pid:[1]'}
            self.assertEqual(eta.classify(job,150,local,{('cloud','b')})['state'],'launching')
            self.assertEqual(eta.classify(job,300,local,{('cloud','b')})['state'],'unknown')
            attempt=job/'attempts/attempt_001';attempt.mkdir(parents=True)
            (attempt/'heartbeat.json').write_text(json.dumps({'hostname':'cloud','boot_id':'b','pid_namespace':'pid:[9]','heartbeat_unix':295}))
            row=eta.classify(job,300,local,{('cloud','b')});self.assertEqual(row['state'],'active');self.assertEqual(row['location'],'cloud')
            (attempt/'result.json').write_text(json.dumps({'status':'failed','finished_at':eta.stamp(300),'end_to_end_seconds':100}))
            row=eta.classify(job,300,local,{('cloud','b')});self.assertEqual(row['state'],'terminal');self.assertEqual(row['status'],'failed')

    def test_all_terminal_does_not_require_future_cloud_capacity(self):
        cell=self.cell();cell['states']={'terminal':300}
        result=eta.eta_projection({'a':cell},['cloud absent'],1000)
        self.assertTrue(result['already_terminal']);self.assertEqual(result['remaining_seconds_range'],[0,0])


class RecoveryEtaTests(unittest.TestCase):
    def test_projection_uses_recovery_rates_not_old_fast_rate(self):
        cell={'planned':300,'states':{'terminal':30},'timeout_seconds':1800,
              'throughput':{'10m':{'all_terminal_count':100,'all_terminal_per_hour':600}},
              'throughput_recovery':{'10m':{'all_terminal_count':3,'all_terminal_per_hour':18},
                                     '20m':{'all_terminal_count':4,'all_terminal_per_hour':12}}}
        result=eta.eta_projection({'cell':cell},[],1000)
        self.assertEqual(result['remaining_seconds_range'],[54000,82800])

    def test_recovery_excludes_old_generation_and_requires_visual_capacity_marker(self):
        rows=[{'started':99,'host_key':('new','b'),'location':'cloud','capacity1':True},
              {'started':101,'host_key':('old','b'),'location':'cloud','capacity1':True},
              {'started':101,'host_key':('new','b'),'location':'cloud','capacity1':False},
              {'started':102,'host_key':('new','b'),'location':'cloud','capacity1':True},
              {'started':103,'host_key':('local','b'),'location':'local','capacity1':True}]
        found=eta.recovery_rows(rows,{'key':('new','b')},100,visual=True)
        self.assertEqual([r['started'] for r in found],[102,103])

    def test_retired_original_is_not_selected_over_newer_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);replacement=root/'replacements/one-ops2';replacement.mkdir(parents=True)
            def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
            put(replacement/'request.json',{'name':'one-ops2','harness':'dsh','strategy':'visual','requested_at_unix':100})
            put(replacement/'response.json',{'state':'submitted'})
            for name,started in [('old',20),('new',120),('other',110)]:
                node=root/'runtime/nodes'/name
                put(node/'telemetry.json',{'hostname':name,'boot_id':'b','pid_namespace':'pid:[1]'})
                put(node/'dsh-visual/bootstrap.json',{'cell':'dsh/visual','started_at_unix':started})
            put(root/'runtime/nodes/old/retired.json',{'hostname':'old','boot_id':'b','pid_namespace':'pid:[1]'})
            all_nodes,bindings,generations=eta.discover_cloud(root,'local',root/'replacements')
            self.assertEqual(len(all_nodes),3)
            self.assertEqual(bindings['dsh/visual']['key'],('new','b'))
            self.assertEqual(generations['dsh/visual']['name'],'one-ops2')
            rate=root/'rate-replacements/one-ops3'
            put(rate/'request.json',{'name':'one-ops3','harness':'dsh','strategy':'visual','requested_at_unix':150})
            put(rate/'response.json',{'state':'submitted'})
            _,bindings,generations=eta.discover_cloud(root,'local',root/'replacements')
            self.assertEqual(generations['dsh/visual']['name'],'one-ops3')
            self.assertNotIn('dsh/visual',bindings)  # Old 8-worker bootstrap cannot count as recovered 4-worker pool.
            node=root/'runtime/nodes/new4'
            put(node/'telemetry.json',{'hostname':'new4','boot_id':'b','pid_namespace':'pid:[4]'})
            put(node/'dsh-visual/bootstrap.json',{'cell':'dsh/visual','started_at_unix':160})
            _,bindings,_=eta.discover_cloud(root,'local',root/'replacements')
            self.assertEqual(bindings['dsh/visual']['key'],('new4','b'))


class ConditionalPlanningTests(unittest.TestCase):
    def test_four_worker_timeout_scenario_unknown_excluded_and_completed_separate(self):
        cell={'states':{'pending':8,'active':4,'terminal':5,'unknown':2},'terminal_statuses':{'completed':3,'timeout':2},
              'timeout_seconds':1800,'calibration_completed_duration':{'count':3,'median_seconds':600},
              'calibration_startup_duration':{'median_seconds':10,'p90_seconds':20}}
        result=eta.conditional_projection({'one':cell},{'active_workers_per_cloud_instance':4},1000)
        self.assertEqual(result['remaining_seconds_range'],[1830,9900])
        self.assertEqual(result['unknown_claims_excluded'],2)
        self.assertEqual(result['native_completed_so_far'],3)
        self.assertEqual(result['maximum_native_completed_from_known_work_without_retry'],15)
        self.assertFalse(result['all_planned_terminal_guaranteed'])
        self.assertTrue(result['utc_range'][0].endswith('+00:00'))
        self.assertTrue(result['beijing_range'][0].endswith('+08:00'))

    def test_no_completed_calibration_does_not_invent_fast_duration(self):
        cell={'states':{'pending':10},'terminal_statuses':{},'timeout_seconds':1800,
              'calibration_completed_duration':{'count':0,'median_seconds':None}}
        self.assertFalse(eta.conditional_projection({'one':cell},{'active_workers_per_cloud_instance':4},1000)['available'])


if __name__=='__main__':unittest.main()
