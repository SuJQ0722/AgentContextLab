from pathlib import Path
import hashlib
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
    def test_io3_recovery_uses_new_worker_host_time_and_reservation_latency(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);attempt=job/'attempts/attempt_001';attempt.mkdir(parents=True);(job/'claim').mkdir()
            (job/'claim/owner.json').write_text(json.dumps({'hostname':'old','boot_id':'old','claimed_at':eta.stamp(100)}))
            (attempt/'worker-started.json').write_text(json.dumps({'hostname':'new','boot_id':'new','started_at':eta.stamp(1600)}))
            (attempt/'result.json').write_text(json.dumps({'status':'completed','finished_at':eta.stamp(1800),
                'end_to_end_seconds':200,'worker_identity':{'hostname':'new','boot_id':'new'}}))
            (attempt/'claim-publication-recovery-dispatch.json').write_text(json.dumps({'reserved_at':eta.stamp(1590)}))
            (attempt/'route-lineage.json').write_text(json.dumps({'runtime_route_version':'bc-v3-fixed-routes-v2','route_plan_sha256':'p'}))
            row=eta.classify(job,1801,{'hostname':'local','boot_id':'b','pid_namespace':'ns'},{('new','new'),('old','old')})
            self.assertEqual(row['host_key'],('new','new'));self.assertEqual(row['started'],1600)
            self.assertEqual(row['claimed'],100);self.assertEqual(row['startup_seconds'],10)
            self.assertEqual(eta.recovery_rows([row],{'key':('new','new'),'required_route_plan_sha256':'p'},1500),[row])
            self.assertIn('run_bc_campaign_v3_routes2_io3.py',eta.VISUAL_CONTROLLER_ENTRIES)

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


class FixedRouteEtaTests(unittest.TestCase):
    def test_unequal_routes_no_held_work_still_cannot_use_aggregate_throughput(self):
        cell=MetadataEtaTests().cell()
        status={'enabled':True,'held_pending':0,'reasons':[]}
        result=eta.eta_projection({'cell':cell},[],1000,status)
        self.assertFalse(result['available']);self.assertIn('Per-route',result['reasons'][0])
        cell['states']={'terminal':300}
        self.assertTrue(eta.eta_projection({'cell':cell},[],1000,status)['already_terminal'])

    def test_bound_v2_selection_supersedes_v1_and_never_falls_back_on_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            one={'version':'bc-v3-fixed-routes-v1','assignments':[]}
            (root/'route-plan-v1.json').write_text(json.dumps(one))
            two={'version':'bc-v3-fixed-routes-v2','parent_route_plan_sha256':'a'*64,'assignments':[]}
            path=root/'route-plan-v2.json';path.write_text(json.dumps(two))
            self.assertEqual(eta.selected_route_plan(root)[0]['version'],one['version'])
            binding={'version':two['version'],'route_plan_path':str(path),
                     'route_plan_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'parent_route_plan_sha256':'a'*64}
            (root/'runtime/routes2-plan-binding.json').write_text(json.dumps(binding))
            self.assertEqual(eta.selected_route_plan(root)[0]['version'],two['version'])
            path.write_text(path.read_text()+' ')
            with self.assertRaisesRegex(ValueError,'SHA mismatch'):eta.selected_route_plan(root)

    def test_cap_zero_pending_withholds_full_eta_and_optimistic_projection(self):
        plan={'jobs':[{'question_id':'q1','repeat':1},{'question_id':'q2','repeat':1},
                      {'question_id':'q3','repeat':1}]}
        routes={'assignments':[{'question_id':'q1','repeat':1,'actual_route':'held'},
                               {'question_id':'q2','repeat':1,'actual_route':'held'},
                               {'question_id':'q3','repeat':1,'actual_route':'open'}]}
        dispatch={'active_workers_per_cloud_instance':16,'per_route_cloud_caps':{'held':0,'open':15},
                  'per_route_local_caps':{'held':0,'open':2}}
        status=eta.route_availability(plan,[{'state':'pending'},{'state':'terminal'},{'state':'pending'}],routes,dispatch)
        self.assertEqual(status['held_pending'],1)
        self.assertEqual(status['routes']['held']['states'],{'pending':1,'terminal':1})
        self.assertFalse(eta.conditional_projection({},dispatch,1000,status)['available'])
        cell=MetadataEtaTests().cell()
        self.assertFalse(eta.eta_projection({'cell':cell},status['reasons'],1000)['available'])
        # A pending route with positive local capacity is not globally held.
        dispatch['per_route_local_caps']['held']=1
        self.assertEqual(eta.route_availability(plan,[{'state':'pending'}]*3,routes,dispatch)['held_pending'],0)

    def test_missing_route_assignments_fail_closed_and_completed_work_not_held(self):
        dispatch={'per_route_cloud_caps':{'r':0},'per_route_local_caps':{'r':0}}
        plan={'jobs':[{'question_id':'q','repeat':1}]}
        state=eta.route_availability(plan,[{'state':'pending'}],{},dispatch)
        self.assertEqual(state['missing_assignments'],1);self.assertTrue(state['reasons'])
        state=eta.route_availability(plan,[{'state':'terminal'}],{},dispatch)
        self.assertEqual(state['missing_assignments'],0);self.assertFalse(state['reasons'])

    def test_routes_recovery_excludes_old_local_and_prior_host(self):
        binding={'key':('new','b'),'generation':{'operational_dispatch':{'version':'cloud-dispatch-routes-v1'}}}
        rows=[{'started':110,'host_key':('new','b'),'location':'cloud','route_runtime':True},
              {'started':110,'host_key':('old','b'),'location':'cloud','route_runtime':True},
              {'started':110,'host_key':('local','b'),'location':'local','route_runtime':False},
              {'started':90,'host_key':('new','b'),'location':'cloud','route_runtime':True}]
        self.assertEqual(eta.recovery_rows(rows,binding,100),rows[:1])
        binding['required_route_plan_sha256']='new'
        for row in rows:row['route_plan_sha256']='old'
        self.assertEqual(eta.recovery_rows(rows,binding,100),[])
        rows[0]['route_plan_sha256']='new'
        self.assertEqual(eta.recovery_rows(rows,binding,100),rows[:1])

    def test_ops5_discovery_replaces_ops4_and_latest_cutoff_not_earliest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def put(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
            for directory,name,moment in [('final-rate-replacements','ops4',100),('routes1-replacements','ops5',200)]:
                receipt=root/directory/name
                put(receipt/'request.json',{'name':name,'harness':'hermes','strategy':'visual','requested_at_unix':moment,
                                           'operational_dispatch':{'version':'cloud-dispatch-routes-v1' if name=='ops5' else 'old'}})
                put(receipt/'response.json',{'state':'submitted'})
                node=root/'runtime/nodes'/name
                put(node/'telemetry.json',{'hostname':name,'boot_id':'b'})
                put(node/'hermes-visual/bootstrap.json',{'cell':'hermes/visual','started_at_unix':moment+10})
            _,bindings,generations=eta.discover_cloud(root,'local',root/'replacement-submissions')
            self.assertEqual(bindings['hermes/visual']['key'],('ops5','b'))
            self.assertEqual(generations['hermes/visual']['calibration_not_before_unix'],200)
            receipt=root/'routes2-replacements/ops6'
            put(receipt/'request.json',{'name':'ops6','harness':'hermes','strategy':'visual','requested_at_unix':300,
                                       'operational_dispatch':{'version':'cloud-dispatch-routes-v1'}})
            put(receipt/'response.json',{'state':'submitted'})
            put(root/'runtime/nodes/ops6/telemetry.json',{'hostname':'ops6','boot_id':'c'})
            put(root/'runtime/nodes/ops6/hermes-visual/bootstrap.json',{'cell':'hermes/visual','started_at_unix':310})
            _,bindings,generations=eta.discover_cloud(root,'local',root/'replacement-submissions')
            self.assertEqual(bindings['hermes/visual']['key'],('ops6','c'))
            self.assertEqual(generations['hermes/visual']['calibration_not_before_unix'],300)


class RoutedVisualEtaTests(unittest.TestCase):
    def lineage(self,attempt,harness):
        spec=attempt/'runtime-spec.json';spec.write_text('{"offline":"metadata fixture"}')
        names=['scripts/hermes_bc_worker_routes1.py','scripts/hermes_bc_worker_v3.py','scripts/hermes_native_vision_worker_v2.py',
               'scripts/run_dsh_eval_v3_routes1.py','scripts/dsh_image_preservation_capacity1.py',
               'scripts/dsh_wire_image_guard_routes1.mjs','scripts/dsh_wire_expectations_routes1.mjs']
        return {'strategy':'visual','harness':harness,'question_id':'q_001','repeat':1,'job_id':harness+'/visual/q_001_r01',
                'actual_route':'route','runtime_route_version':'bc-v3-fixed-routes-v2','route_plan_sha256':'b'*64,
                'runtime_config_sha256':'c'*64,'runtime_spec_path':str(spec),
                'runtime_spec_sha256':hashlib.sha256(spec.read_bytes()).hexdigest(),
                'implementation_sha256':{name:hashlib.sha256((eta.ROOT/name).read_bytes()).hexdigest() for name in names}}

    def test_hermes_native_guard_source_evidence_without_outer_capacity_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt=Path(tmp);lineage=self.lineage(attempt,'hermes');(attempt/'native/metrics').mkdir(parents=True)
            (attempt/'native/attempt-started.json').write_text(json.dumps({'job_id':lineage['job_id']}))
            policy=attempt/'native/metrics/policy.jsonl';policy.write_text(json.dumps({'verified':True,'strategy':'visual','engine':'visual'})+'\n')
            self.assertTrue(eta.visual_runtime_evidence(attempt,lineage)['verified'])
            lineage['implementation_sha256']['scripts/hermes_native_vision_worker_v2.py']='f'*64
            self.assertFalse(eta.visual_runtime_evidence(attempt,lineage)['verified'])

    def test_dsh_requires_native_cap64_disabled_offload_and_matching_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            attempt=Path(tmp);lineage=self.lineage(attempt,'dsh');path=attempt/'native/visual_native/q_001/manifest.json';path.parent.mkdir(parents=True)
            manifest={'image_transport':'original-image-bytes-capacity1','canonical_strategy':'visual','question_id':'q_001','repeat':1,
                      'model':'route','config_sha256':lineage['runtime_config_sha256'],'route_lineage':lineage,
                      'runtime_lineage':{'runtime_version':'original-image-bytes-capacity1','transport_diff':{
                          'maxRequestImageBytes':{'after':64*1024*1024},'compaction-image-offload':{'after':'disabled'}}}}
            path.write_text(json.dumps(manifest));self.assertTrue(eta.visual_runtime_evidence(attempt,lineage)['verified'])
            manifest['runtime_lineage']['transport_diff']['maxRequestImageBytes']['after']=20*1024*1024
            path.write_text(json.dumps(manifest));self.assertFalse(eta.visual_runtime_evidence(attempt,lineage)['verified'])
            manifest['runtime_lineage']['transport_diff']['maxRequestImageBytes']['after']=64*1024*1024
            entry='scripts/run_dsh_eval_v3_routes2_io3.py';digest=hashlib.sha256((eta.ROOT/entry).read_bytes()).hexdigest()
            sidecar=attempt/'claim-publication-io3.json';sidecar.write_text(json.dumps({'version':'bc-v3-claim-publication-io3','implementation_sha256':{entry:digest}}))
            manifest['operational_maintenance']={'version':'bc-v3-claim-publication-io3','sidecar_path':str(sidecar),
                'sidecar_sha256':hashlib.sha256(sidecar.read_bytes()).hexdigest(),'native_entry':entry,'native_entry_sha256':digest}
            path.write_text(json.dumps(manifest));self.assertTrue(eta.visual_runtime_evidence(attempt,lineage)['verified'])
            manifest['operational_maintenance']['native_entry_sha256']='f'*64
            path.write_text(json.dumps(manifest));self.assertFalse(eta.visual_runtime_evidence(attempt,lineage)['verified'])
            manifest['operational_maintenance']['native_entry_sha256']=digest
            manifest['route_lineage']={**lineage,'route_plan_sha256':'f'*64}
            path.write_text(json.dumps(manifest));self.assertFalse(eta.visual_runtime_evidence(attempt,lineage)['verified'])


if __name__=='__main__':unittest.main()
