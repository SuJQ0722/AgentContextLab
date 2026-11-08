import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import monitor_bc_campaign_v3 as monitor


class RawAccountingTests(unittest.TestCase):
    def test_unknown_cache_is_not_zero_and_zero_is_known(self):
        result = monitor.aggregate([
            {'raw_provider_usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12}},
            {'raw_provider_usage': {'prompt_tokens': 8, 'completion_tokens': 1, 'total_tokens': 9, 'prompt_tokens_details': {'cached_tokens': 0}}},
            {'raw_provider_usage': {'prompt_tokens': 4, 'completion_tokens': None, 'total_tokens': None, 'prompt_tokens_details': {'cached_tokens': None}}},
        ])
        fields = result['fields']
        self.assertEqual(fields['prompt']['complete_total'], 22)
        self.assertEqual(fields['cached_input']['known_count'], 1)
        self.assertEqual(fields['cached_input']['known_subtotal'], 0)
        self.assertEqual(fields['cached_input']['missing_count'], 2)
        self.assertIsNone(fields['cached_input']['complete_total'])
        self.assertEqual(fields['noncache_input']['known_subtotal'], 8)
        self.assertEqual(fields['total']['known_subtotal'], 21)
        self.assertIsNone(fields['total']['complete_total'])

    def test_conservation_is_per_request_and_conflicts_are_unknown(self):
        values, errors = monitor.analyze_usage({'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 13,
                                               'prompt_cache_hit_tokens': 4, 'prompt_cache_miss_tokens': 7})
        self.assertIn('cache_split_not_conserved', errors)
        self.assertIn('prompt_output_total_not_conserved', errors)
        self.assertIsNone(values['cached_input'])
        values, errors = monitor.analyze_usage({'prompt_tokens': 10, 'input_tokens': 11, 'prompt_cache_hit_tokens': 0})
        self.assertIsNone(values['prompt'])
        self.assertIsNone(values['noncache_input'])
        self.assertIn('prompt_invalid_or_conflicting', errors)

    def test_raw_http_wins_dedup_final_inflight_and_summary(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td); (metrics / 'wire').mkdir()
            def write(path, rows):
                path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
            raw = {'request_id': 'a', 'purpose': 'agent', 'response_complete': True,
                   'raw_provider_usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
                                          'prompt_tokens_details': {'cached_tokens': 0}}}
            write(metrics / 'wire/raw-usage.jsonl', [
                {'request_id': 'a', 'event': 'response_started'}, raw, raw,
                {'request_id': 'b', 'purpose': 'compaction', 'event': 'response_started'},
                {'request_id': 'c', 'purpose': 'compaction', 'response_complete': False,
                 'raw_provider_usage': {'prompt_tokens': 500, 'completion_tokens': 999}},
            ])
            write(metrics / 'calls.jsonl', [{'call_id': 'sdk-a', 'usage': {'inputTokens': 1000000},
                                            'client_stream_seconds': 2}])
            issues = []
            rows, states, purposes, latency = monitor.accounting(metrics, 'dsh', issues)
            self.assertEqual(len(rows), 3)
            self.assertEqual(states['http_terminal'], 2)
            self.assertEqual(states['http_response_inflight'], 1)
            self.assertEqual(monitor.aggregate(rows)['fields']['prompt']['known_subtotal'], 10)
            self.assertEqual(purposes['compaction']['fields']['prompt']['missing_count'], 2)
            self.assertEqual(latency['sdk_client_seconds_known_subtotal'], 2)
            self.assertEqual(issues, [])

    def test_missing_raw_cannot_use_normalized_defaults(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td)
            (metrics / 'calls.jsonl').write_text(json.dumps({'call_id': 'a', 'usage': {'inputTokens': 9, 'cacheReadTokens': 0}}) + '\n')
            issues = []
            rows, _, _, _ = monitor.accounting(metrics, 'dsh', issues)
            self.assertIsNone(monitor.aggregate(rows)['fields']['prompt']['complete_total'])
            self.assertEqual(monitor.aggregate(rows)['fields']['prompt']['missing_count'], 1)
            self.assertEqual(issues[0]['kind'], 'missing_raw_http_usage')

    def test_sent_before_headers_is_unknown_without_double_counting_finished_requests(self):
        with tempfile.TemporaryDirectory() as td:
            metrics = Path(td); (metrics / 'wire').mkdir()
            def write(name, rows):
                (metrics / 'wire' / name).write_text(''.join(json.dumps(r)+'\n' for r in rows))
            write('requests.jsonl', [{'request_id': key, 'request_sent': True} for key in ['a', 'b']] +
                  [{'request_id': 'blocked', 'request_sent': False, 'guard_error': 'not sent'}])
            write('raw-usage.jsonl', [{'request_id': 'a', 'event': 'response_started'},
                  {'request_id': 'a', 'purpose': 'agent', 'response_complete': True,
                   'raw_provider_usage': {'prompt_tokens': 10, 'completion_tokens': 2, 'total_tokens': 12,
                                          'prompt_tokens_details': {'cached_tokens': 0}}}])
            rows, states, _, _ = monitor.accounting(metrics, 'dsh', [])
            totals = monitor.aggregate(rows)
            self.assertEqual(len(rows), 2)
            self.assertEqual(states['http_sent_without_response'], 1)
            self.assertEqual(totals['fields']['total']['known_subtotal'], 12)
            self.assertEqual(totals['fields']['total']['missing_count'], 1)
            self.assertIsNone(totals['fields']['total']['complete_total'])
            # Also preserve the missing first-ever response, without duplicating SDK starts.
            (metrics / 'wire/raw-usage.jsonl').unlink()
            rows, _, _, _ = monitor.accounting(metrics, 'dsh', [])
            self.assertEqual(len(rows), 2)


class CloudTelemetryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.registry=self.root/'submissions';self.registry.mkdir()
        self.local={'hostname':'local','boot_id':'boot-local','pid_namespace':'pid:[1]'}
        self.counts={'visible_total':11,'visible_live':10,'core_v3_subtree_live':5}
        self.now=1800000000
    def tearDown(self):self.temp.cleanup()
    def submission(self,name='one',state='submitted',**kw):
        (self.registry/(name+'.json')).write_text(json.dumps({'name':name,'state':state,'mode':'live','workers':32,**kw}))
    def node(self,name,hostname='remote',boot='boot-remote',age=0,**kw):
        path=self.root/'runtime/nodes'/name/'telemetry.json';path.parent.mkdir(parents=True)
        value={'schema':'bc-v3-node-telemetry-v1','timestamp':datetime.fromtimestamp(self.now-age,timezone.utc).isoformat(),
               'hostname':hostname,'boot_id':boot,'pid_namespace':'pid:[2]',
               'processes':{'visible_total':21,'visible_live':20,'core_v3_subtree_live':15},**kw}
        path.write_text(json.dumps(value));return path
    def inspect(self,**kw):
        return monitor.node_process_totals(self.root,self.counts,now_unix=self.now,local_identity=self.local,
                                            submissions_root=self.registry,**kw)
    def test_fresh_cloud_coverage_and_worker_concurrency_is_not_node_count(self):
        self.submission(argv=['sco','--worker-nodes','1']);self.node('one')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        self.assertTrue(total['complete']);self.assertEqual(total['fields']['visible_live']['complete_total'],30)
        self.assertEqual(self.counts['visible_live'],10)  # Existing local record is untouched.
    def test_missing_cloud_reports_are_unknown_not_zero(self):
        self.submission('one');self.submission('two');self.node('one')
        cloud,total=self.inspect()
        self.assertEqual(cloud['missing_fresh_nodes'],1);self.assertFalse(total['complete'])
        self.assertEqual(total['fields']['visible_live']['known_subtotal'],30)
        self.assertIsNone(total['fields']['visible_live']['complete_total'])
    def test_stale_and_absent_counters_are_not_summed_as_zero(self):
        self.submission();self.node('old',age=91)
        cloud,total=self.inspect();self.assertEqual(cloud['nodes'][0]['status'],'stale')
        self.assertEqual(total['fields']['visible_live']['known_subtotal'],10);self.assertFalse(total['complete'])
        (self.root/'runtime/nodes/old/telemetry.json').unlink()
        self.node('missing',processes={'visible_total':21,'core_v3_subtree_live':15})
        cloud,total=self.inspect();self.assertFalse(total['complete'])
        self.assertEqual(total['fields']['visible_live']['missing_count_nodes'],1)
        self.assertIsNone(total['fields']['visible_live']['complete_total'])
    def test_local_and_duplicate_host_boot_are_not_double_counted(self):
        self.submission();self.node('self','local','boot-local',pid_namespace='pid:[1]')
        self.node('old-copy',age=10,processes={'visible_total':99,'visible_live':99,'core_v3_subtree_live':99})
        self.node('new-copy',age=1)
        cloud,total=self.inspect();self.assertTrue(total['complete'])
        self.assertEqual(total['fields']['visible_live']['complete_total'],30)
        self.assertEqual({n['status'] for n in cloud['nodes']},{'local_duplicate','duplicate_superseded','fresh'})
    def test_bad_registry_future_clock_and_namespace_conflict_are_explicit(self):
        (self.registry/'bad.json').write_text('{')
        self.node('future',age=-30)
        cloud,total=self.inspect();self.assertFalse(total['complete']);self.assertIsNone(cloud['expected_active_cloud_nodes'])
        self.assertEqual(cloud['nodes'][0]['status'],'future_timestamp')
        (self.registry/'bad.json').unlink();(self.root/'runtime/nodes/future/telemetry.json').unlink()
        self.node('self','local','boot-local',pid_namespace='pid:[999]')
        cloud,total=self.inspect();self.assertFalse(total['complete'])
        self.assertEqual(cloud['issues'][0]['kind'],'local_pid_namespace_conflict')
    def test_ended_submissions_are_not_expected_and_stale_local_is_incomplete(self):
        self.submission(state='submission_failed');self.submission('done',state='completed')
        cloud,total=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],0);self.assertTrue(total['complete'])
        cloud,total=self.inspect(local_observed_unix=self.now-91);self.assertFalse(total['complete'])

    def test_retired_namespace_does_not_block_complete_but_missing_stays_unknown(self):
        self.submission()
        old = self.node('old', age=1000)
        (old.parent / 'retired.json').write_text(json.dumps({'hostname':'remote', 'boot_id':'boot-remote',
            'pid_namespace':'pid:[2]', 'job_name':'old-job', 'retired_at':'2026-11-08T09:00:00+00:00'}))
        current = self.node('current', pid_namespace='pid:[3]')
        cloud, total = self.inspect()
        self.assertTrue(total['complete'])
        self.assertEqual(cloud['unusable_telemetry_nodes'], 0)
        self.assertEqual(cloud['fresh_unique_remote_nodes'], 1)
        self.assertEqual({row['status'] for row in cloud['nodes']}, {'retired_namespace','fresh'})
        self.assertEqual(total['fields']['visible_live']['complete_total'], 30)
        current.unlink()
        cloud, total = self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'], 1)
        self.assertEqual(cloud['missing_fresh_nodes'], 1)
        self.assertIsNone(total['fields']['visible_live']['complete_total'])

    def test_retirement_cannot_exclude_new_namespace_on_same_host_boot(self):
        self.submission()
        path = self.node('reused-directory', pid_namespace='pid:[3]')
        (path.parent / 'retired.json').write_text(json.dumps({'hostname':'remote', 'boot_id':'boot-remote',
            'pid_namespace':'pid:[2]', 'job_name':'old-job', 'retired_at':'2026-11-08T09:00:00+00:00'}))
        cloud, total = self.inspect()
        self.assertEqual(cloud['nodes'][0]['status'], 'fresh')
        self.assertTrue(total['complete'])
        self.assertEqual(cloud['fresh_unique_remote_nodes'], 1)

    def retired_original(self, name='one', strategy='none'):
        self.submission(name)
        old=self.node('old-'+name,hostname='old-'+name,age=1000)
        marker={'hostname':'old-'+name,'boot_id':'boot-remote','pid_namespace':'pid:[2]','job_name':name}
        (old.parent/'retired.json').write_text(json.dumps(marker))
        exited=old.parent/'exit.json';exited.write_text(json.dumps({'controller_exit_code':0,'stopped':True}))
        directory=self.registry.parent/'reader-resume'/name;directory.mkdir(parents=True)
        request={'job':{'name':name,'strategy':strategy},'evidence':{'acp_state':'SUCCEEDED',
            'node_directory':str(old.parent),'bootstrap_exit':str(exited),'hostname':marker['hostname'],
            'retired_boot_id':marker['boot_id'],'retired_pid_namespace':marker['pid_namespace']}}
        (directory/'request.json').write_text(json.dumps(request))
        (directory/'response.json').write_text(json.dumps({'state':'rejected','returncode':1,
             'stderr':'{"reason":"tjUpdateNotSupportStart"}'}))
        return directory

    def replacement(self,name='one',state='submitted'):
        directory=self.registry.parent/'replacement-submissions'/(name+'-ops2');directory.mkdir(parents=True)
        (directory/'request.json').write_text(json.dumps({'name':name+'-ops2','replaces':name,
            'argv':['sco','--worker-nodes','1'],'operational_dispatch':{'active_workers_per_cloud_instance':8},'worker_ceiling':32}))
        (directory/'response.json').write_text(json.dumps({'state':state}))
        return directory

    def test_replacement_retires_old_count_and_keeps_actual_worker_count_separate(self):
        self.retired_original();self.replacement();self.node('new',hostname='new',pid_namespace='pid:[3]')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        self.assertEqual(len(cloud['retired_generations']),1)
        self.assertEqual(cloud['active_submissions'][0]['active_workers_per_instance'],8)
        self.assertEqual(cloud['active_submissions'][0]['worker_ceiling'],32)
        self.assertTrue(total['complete'])
        self.assertEqual(json.loads((self.registry/'one.json').read_text())['state'],'submitted')

    def test_unknown_replacement_counts_one_but_never_complete_and_rejection_zero(self):
        self.retired_original();directory=self.replacement(state='unknown')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        self.assertEqual(cloud['missing_fresh_nodes'],1);self.assertFalse(total['complete'])
        self.assertIn('replacement_submission_outcome_unknown',[x['kind'] for x in cloud['issues']])
        (directory/'response.json').write_text(json.dumps({'state':'rejected'}))
        cloud,total=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],0)
        self.assertEqual(cloud['planned_not_running'][0]['reason'],'replacement_rejected')

    def test_visual_hold_not_missing_active_node_but_retirement_must_be_proven(self):
        directory=self.retired_original(strategy='visual')
        cloud,total=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],0)
        self.assertEqual(cloud['missing_fresh_nodes'],0);self.assertTrue(total['complete'])
        self.assertEqual(cloud['holds'][0]['reason'],'visual_intentionally_held')
        (directory/'response.json').write_text(json.dumps({'state':'unknown'}))
        cloud,total=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        self.assertFalse(total['complete'])

    def rate_replacement(self,state='submitted'):
        self.retired_original();self.replacement()
        node=self.node('old-ops2',hostname='old-ops2',age=1000)
        marker={'hostname':'old-ops2','boot_id':'boot-remote','pid_namespace':'pid:[2]','job_name':'one-ops2'}
        (node.parent/'retired.json').write_text(json.dumps(marker))
        exited=node.parent/'exit.json';exited.write_text(json.dumps({'controller_exit_code':0,'stopped':True}))
        directory=self.registry.parent/'rate-replacements/one-ops3';directory.mkdir(parents=True)
        request={'name':'one-ops3','replaces':'one-ops2','original_name':'one','generation':'ops3',
            'argv':['sco','--worker-nodes','1'],'operational_dispatch':{'active_workers_per_cloud_instance':4},'worker_ceiling':32,
            'evidence':{'acp_state':'SUCCEEDED','node_directory':str(node.parent),'bootstrap_exit':str(exited),
                'hostname':'old-ops2','retired_boot_id':'boot-remote','retired_pid_namespace':'pid:[2]'}}
        (directory/'request.json').write_text(json.dumps(request))
        (directory/'response.json').write_text(json.dumps({'state':state}))
        return directory,node

    def test_three_generations_count_only_latest_and_actual_four(self):
        self.rate_replacement();self.node('new-ops3',hostname='new-ops3',pid_namespace='pid:[4]')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        self.assertEqual(len(cloud['retired_generations']),2)
        self.assertEqual(cloud['active_submissions'][0]['name'],'one-ops3')
        self.assertEqual(cloud['active_submissions'][0]['active_workers_per_instance'],4)
        self.assertEqual(cloud['active_submissions'][0]['worker_ceiling'],32)
        self.assertTrue(total['complete'])

    def test_rate_unknown_never_zero_and_unproven_parent_not_hidden(self):
        directory,node=self.rate_replacement(state='unknown')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1);self.assertFalse(total['complete'])
        self.assertIn('rate_replacement_submission_outcome_unknown',[r['kind'] for r in cloud['issues']])
        marker=json.loads((node.parent/'retired.json').read_text());marker['pid_namespace']='pid:[wrong]'
        (node.parent/'retired.json').write_text(json.dumps(marker))
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],2)
        self.assertIn('rate_parent_retirement_unproven',[r['kind'] for r in cloud['issues']])
        self.assertFalse(total['complete'])

    def test_rate_controller_only_drain_requires_exact_identity_and_saved_hash(self):
        directory,node=self.rate_replacement()
        request=json.loads((directory/'request.json').read_text())
        (node.parent/'exit.json').write_text(json.dumps({'controller_exit_code':0,'stopped':False}))
        boot=node.parent/'bootstrap.json'
        identity={'hostname':'old-ops2','boot_id':'boot-remote','pid_namespace':'pid:[2]'}
        boot.write_text(json.dumps({**identity,'controller_pid':42}))
        status=self.root/'controllers/old/status.json';status.parent.mkdir(parents=True)
        status.write_text(json.dumps({**identity,'pid':42,'start_identity':'99','stop_dispatch':True,'active_local':0}))
        import hashlib
        request['evidence'].update(bootstrap_path=str(boot),clean_drain={'kind':'controller_stop_and_drain',
            'status_path':str(status),'status_sha256':hashlib.sha256(status.read_bytes()).hexdigest()})
        (directory/'request.json').write_text(json.dumps(request))
        cloud,_=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],1)
        value=json.loads(status.read_text());value['active_local']=1;status.write_text(json.dumps(value))
        cloud,_=self.inspect();self.assertEqual(cloud['expected_active_cloud_nodes'],2)

    def test_final_ops4_replaces_ops3_once_and_records_actual_one(self):
        self.rate_replacement()
        node=self.node('old-ops3',hostname='old-ops3',age=1000)
        marker={'hostname':'old-ops3','boot_id':'boot-remote','pid_namespace':'pid:[3]','job_name':'one-ops3'}
        telemetry=json.loads(node.read_text());telemetry['pid_namespace']='pid:[3]';node.write_text(json.dumps(telemetry))
        (node.parent/'retired.json').write_text(json.dumps(marker))
        exit_path=node.parent/'exit.json';exit_path.write_text(json.dumps({'controller_exit_code':0,'stopped':True}))
        directory=self.registry.parent/'final-rate-replacements/one-ops4';directory.mkdir(parents=True)
        request={'name':'one-ops4','replaces':'one-ops3','original_name':'one','generation':'ops4',
            'argv':['sco','--worker-nodes','1'],'active_workers_this_cell':1,
            'operational_dispatch':{'active_workers_per_cloud_instance':1,'local_target_workers':2},'worker_ceiling':32,
            'evidence':{'acp_state':'SUCCEEDED','node_directory':str(node.parent),'bootstrap_exit':str(exit_path),
                'hostname':'old-ops3','retired_boot_id':'boot-remote','retired_pid_namespace':'pid:[3]'}}
        (directory/'request.json').write_text(json.dumps(request));(directory/'response.json').write_text(json.dumps({'state':'submitted'}))
        self.node('new-ops4',hostname='new-ops4',pid_namespace='pid:[4]')
        cloud,total=self.inspect()
        self.assertEqual(cloud['expected_active_cloud_nodes'],1);self.assertEqual(len(cloud['retired_generations']),3)
        self.assertEqual(cloud['active_submissions'][0]['name'],'one-ops4')
        self.assertEqual(cloud['active_submissions'][0]['active_workers_per_instance'],1)
        self.assertEqual(cloud['active_submissions'][0]['worker_ceiling'],32);self.assertTrue(total['complete'])

    def test_routes1_ops5_retires_ops4_with_original_receipts_preserved(self):
        self.rate_replacement()
        # Exercise the generic generation overlay directly with an already
        # validated ops4 parent; preceding generation-chain tests cover its origin.
        node=self.node('old-ops4',hostname='old-ops4',age=1000,pid_namespace='pid:[4]')
        marker={'hostname':'old-ops4','boot_id':'boot-remote','pid_namespace':'pid:[4]','job_name':'one-ops4'}
        (node.parent/'retired.json').write_text(json.dumps(marker))
        exit_path=node.parent/'exit.json';exit_path.write_text(json.dumps({'controller_exit_code':0,'stopped':True}))
        directory=self.registry.parent/'routes1-replacements/one-ops5';directory.mkdir(parents=True)
        request={'name':'one-ops5','replaces':'one-ops4','original_name':'one','generation':'ops5',
            'argv':['sco','--worker-nodes','1'],'operational_dispatch':{'active_workers_per_cloud_instance':16},'worker_ceiling':32,
            'evidence':{'acp_state':'SUCCEEDED','node_directory':str(node.parent),'bootstrap_exit':str(exit_path),
                'hostname':'old-ops4','retired_boot_id':'boot-remote','retired_pid_namespace':'pid:[4]'}}
        (directory/'request.json').write_text(json.dumps(request));(directory/'response.json').write_text(json.dumps({'state':'submitted'}))
        retired=[];planned=[];issues=[]
        active=monitor._rate_generations(self.root,self.registry.parent/'absent-rate-dir',
            [{'name':'one-ops4','state':'submitted','expected_nodes':1}],retired,planned,issues)
        self.assertEqual([r['name'] for r in active],['one-ops5'])
        self.assertEqual(active[0]['active_workers_per_instance'],16)
        self.assertEqual(active[0]['worker_ceiling'],32);self.assertEqual(issues,[])

    def test_routes2_ops6_retires_ops5_with_original_receipts_preserved(self):
        self.rate_replacement()
        # Exercise the generic generation overlay directly with an already
        # validated ops5 parent; preceding generation-chain tests cover its origin.
        node=self.node('old-ops5',hostname='old-ops5',age=1000,pid_namespace='pid:[5]')
        marker={'hostname':'old-ops5','boot_id':'boot-remote','pid_namespace':'pid:[5]','job_name':'one-ops5'}
        (node.parent/'retired.json').write_text(json.dumps(marker))
        exit_path=node.parent/'exit.json';exit_path.write_text(json.dumps({'controller_exit_code':0,'stopped':True}))
        directory=self.registry.parent/'routes2-replacements/one-ops6';directory.mkdir(parents=True)
        request={'name':'one-ops6','replaces':'one-ops5','original_name':'one','generation':'ops6',
            'argv':['sco','--worker-nodes','1'],'operational_dispatch':{'active_workers_per_cloud_instance':16},'worker_ceiling':32,
            'evidence':{'acp_state':'SUCCEEDED','node_directory':str(node.parent),'bootstrap_exit':str(exit_path),
                'hostname':'old-ops5','retired_boot_id':'boot-remote','retired_pid_namespace':'pid:[5]'}}
        (directory/'request.json').write_text(json.dumps(request));(directory/'response.json').write_text(json.dumps({'state':'submitted'}))
        retired=[];planned=[];issues=[]
        active=monitor._rate_generations(self.root,self.registry.parent/'absent-rate-dir',
            [{'name':'one-ops5','state':'submitted','expected_nodes':1}],retired,planned,issues)
        self.assertEqual([r['name'] for r in active],['one-ops6'])
        self.assertEqual(active[0]['active_workers_per_instance'],16)
        self.assertEqual(active[0]['worker_ceiling'],32);self.assertEqual(issues,[])


class FailedNamespaceEvidenceTests(unittest.TestCase):
    def setUp(self):
        import hashlib
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'campaign'; self.root.mkdir()
        self.node = self.root / 'runtime/nodes/pt-uid-worker-0-boot'
        self.cell = self.node / 'hermes-summarize'; self.cell.mkdir(parents=True)
        self.proofs = Path(self.temp.name) / 'proofs'; self.proofs.mkdir()
        identity = {'hostname':'pt-uid-worker-0','boot_id':'boot','pid_namespace':'pid:[8]'}
        self.marker = {**identity,'job_name':'one-ops5','reason':'failed_startup_namespace_terminated'}
        (self.node/'retired.json').write_text(json.dumps(self.marker))
        data = {'describe': {'name':'one-ops5','uid':'uid','workspace_name':'rl','state':'FAILED'},
                'bootstrap': {**identity,'cell':'hermes/summarize','started_at_unix':10},
                'exit': {'controller_exit_code':1,'stopped':False,'finished_at_unix':20},
                'inventory': {'cell':'hermes/summarize','claims':[]}}
        proof = {'schema':'acp-terminated-namespace-v1','platform_state':'FAILED',
                 'namespace_terminated':True,'name':'one-ops5','uid':'uid',**identity,'observed_at_unix':30}
        for name, value in data.items():
            path = (self.cell if name in ('bootstrap','exit') else self.proofs) / (name+'.json')
            path.write_text(json.dumps(value));proof[name+'_path']=str(path)
            proof[name+'_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.proof = self.proofs/'terminated-namespace.json';self.proof.write_text(json.dumps(proof))
        self.evidence = {'kind':'failed_startup_namespace_terminated','acp_state':'FAILED',
            'terminated_namespace_evidence_path':str(self.proof),
            'terminated_namespace_evidence_sha256':hashlib.sha256(self.proof.read_bytes()).hexdigest(),
            'node_directory':str(self.node),'bootstrap_exit':proof['exit_path'],
            'hostname':identity['hostname'],'retired_boot_id':'boot','retired_pid_namespace':'pid:[8]'}

    def test_failed_proof_replaces_once_without_claiming_successful_drain(self):
        self.assertTrue(monitor._retired_generation_proven(self.root,'one-ops5',self.evidence))
        registry = self.proofs/'routes2-replacements/one-ops6';registry.mkdir(parents=True)
        request = {'name':'one-ops6','replaces':'one-ops5','original_name':'one','generation':'ops6',
                   'argv':['sco','--worker-nodes','1'],'active_workers_this_cell':16,
                   'worker_ceiling':32,'evidence':self.evidence}
        (registry/'request.json').write_text(json.dumps(request))
        (registry/'response.json').write_text(json.dumps({'state':'submitted'}))
        retired=[];planned=[];issues=[]
        active=monitor._rate_generations(self.root,self.proofs/'rate-replacements',
            [{'name':'one-ops5','expected_nodes':1}],retired,planned,issues)
        self.assertEqual([x['name'] for x in active],['one-ops6'])
        self.assertEqual(retired[0]['state'],'failed_namespace_terminated')
        self.assertEqual(issues,[])

    def test_mutated_platform_proof_and_namespace_are_rejected(self):
        self.evidence['retired_pid_namespace']='pid:[other]'
        self.assertFalse(monitor._retired_generation_proven(self.root,'one-ops5',self.evidence))
        self.evidence['retired_pid_namespace']='pid:[8]'
        proof=json.loads(self.proof.read_text());path=Path(proof['describe_path'])
        description=json.loads(path.read_text());description['state']='RUNNING'
        path.write_text(json.dumps(description))
        self.assertFalse(monitor._retired_generation_proven(self.root,'one-ops5',self.evidence))
        # Even consistently rehashed evidence cannot turn a running namespace into a terminal one.
        import hashlib
        proof['describe_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        self.proof.write_text(json.dumps(proof))
        self.evidence['terminated_namespace_evidence_sha256']=hashlib.sha256(self.proof.read_bytes()).hexdigest()
        self.assertFalse(monitor._retired_generation_proven(self.root,'one-ops5',self.evidence))

    def test_exit_one_without_full_namespace_proof_cannot_retire(self):
        del self.evidence['terminated_namespace_evidence_sha256']
        self.assertFalse(monitor._retired_generation_proven(self.root,'one-ops5',self.evidence))


class TerminalCacheTests(unittest.TestCase):
    def setUp(self):
        monitor._TERMINAL_CACHE.clear()
        self.addCleanup(monitor._TERMINAL_CACHE.clear)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.attempt = Path(self.temp.name)
        self.metrics = self.attempt / 'native/metrics'; self.metrics.mkdir(parents=True)
        self.calls = self.metrics / 'calls.jsonl'
        self.calls.write_text(json.dumps({'call_id':'one','raw_provider_usage':{
            'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})+'\n')
        self.result = self.attempt / 'result.json'
        self.write_result()

    def write_result(self, **changes):
        self.result.write_text(json.dumps({'status':'completed','slot_released':True,
            'unconfirmed_child_termination':[], **changes}))

    def test_terminal_hit_preserves_missing_and_is_deep_copy(self):
        with patch.object(monitor, '_inspect_attempt_uncached', wraps=monitor._inspect_attempt_uncached) as inspect:
            row, usage = monitor.inspect_attempt(self.attempt, 'hermes')
            row['strategy'] = 'mutated'; row['usage']['fields']['prompt']['known_subtotal'] = 999
            usage[0]['raw_provider_usage']['prompt_tokens'] = 999
            again, raw = monitor.inspect_attempt(self.attempt, 'hermes')
            self.assertEqual(inspect.call_count, 1)
            self.assertNotIn('strategy', again)
            self.assertEqual(again['usage']['fields']['prompt']['known_subtotal'], 10)
            self.assertEqual(raw[0]['raw_provider_usage']['prompt_tokens'], 10)
            self.assertIsNone(again['usage']['fields']['cached_input']['complete_total'])

    def test_result_marker_change_invalidates(self):
        with patch.object(monitor, '_inspect_attempt_uncached', wraps=monitor._inspect_attempt_uncached) as inspect:
            monitor.inspect_attempt(self.attempt, 'hermes')
            self.write_result(status='failed', end_to_end_seconds=123)
            row, _ = monitor.inspect_attempt(self.attempt, 'hermes')
            self.assertEqual(inspect.call_count, 2)
            self.assertEqual(row['state'], 'failed')

    def test_active_unknown_and_unconfirmed_cleanup_never_cached(self):
        for state, released, remaining in [('unfinished',False,[]),('unknown',True,[]),
                                            ('interrupted',False,[123]),('completed',True,None)]:
            monitor._TERMINAL_CACHE.clear()
            self.write_result(status=state,slot_released=released,unconfirmed_child_termination=remaining)
            with patch.object(monitor, '_inspect_attempt_uncached', wraps=monitor._inspect_attempt_uncached) as inspect:
                monitor.inspect_attempt(self.attempt,'hermes'); monitor.inspect_attempt(self.attempt,'hermes')
                self.assertEqual(inspect.call_count,2)
            self.assertFalse(monitor._TERMINAL_CACHE)
        self.result.unlink()
        monitor.inspect_attempt(self.attempt,'hermes'); self.assertFalse(monitor._TERMINAL_CACHE)

    def test_terminal_metric_append_and_new_directory_invalidate(self):
        with patch.object(monitor, '_inspect_attempt_uncached', wraps=monitor._inspect_attempt_uncached) as inspect:
            monitor.inspect_attempt(self.attempt,'hermes')
            with self.calls.open('a') as stream: stream.write(json.dumps({'call_id':'two'})+'\n')
            row, _ = monitor.inspect_attempt(self.attempt,'hermes')
            self.assertEqual(inspect.call_count,2)
            self.assertEqual(row['usage']['fields']['prompt']['missing_count'],1)
            newer = self.attempt/'native/second'; newer.mkdir()
            (newer/'calls.jsonl').write_text(json.dumps({'call_id':'three'})+'\n')
            row, _ = monitor.inspect_attempt(self.attempt,'hermes')
            self.assertEqual(inspect.call_count,3)
            self.assertEqual(row['metrics_directories'],2)


class KnownLayoutDiscoveryTests(unittest.TestCase):
    def test_formal_layout_never_recurses_and_late_raw_usage_invalidates(self):
        monitor._TERMINAL_CACHE.clear(); self.addCleanup(monitor._TERMINAL_CACHE.clear)
        with tempfile.TemporaryDirectory() as temporary:
            attempt=Path(temporary)/'jobs/dsh/visual/q_001_r01/attempts/attempt_001'
            attempt.mkdir(parents=True)
            (attempt/'result.json').write_text(json.dumps({'status':'completed','slot_released':True,'unconfirmed_child_termination':[]}))
            with patch.object(Path,'rglob',side_effect=AssertionError('No recursive traversal for formal v3 layout')):
                row,_=monitor.inspect_attempt(attempt,'dsh');self.assertEqual(row['metrics_directories'],0)
                metrics=attempt/'native/visual_native/q_001/workspace/metrics'
                (metrics/'wire').mkdir(parents=True)
                (metrics/'wire/raw-usage.jsonl').write_text(json.dumps({'request_id':'late','response_complete':True,
                    'raw_provider_usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12}})+'\n')
                row,_=monitor.inspect_attempt(attempt,'dsh')
                self.assertEqual(row['metrics_directories'],1)
                self.assertEqual(row['usage']['fields']['prompt']['complete_total'],10)
                self.assertIsNone(row['usage']['fields']['cached_input']['complete_total'])

    def test_hermes_direct_location_and_sliding_window_alias(self):
        attempt=Path('/tmp/jobs/hermes/none/q_001_r01/attempts/attempt_001')
        self.assertEqual(monitor._known_metric_path(attempt,'hermes'),attempt/'native/metrics')
        attempt=Path('/tmp/jobs/dsh/sliding_window/q_001_r01/attempts/attempt_001')
        self.assertEqual(monitor._known_metric_path(attempt,'dsh'),attempt/'native/sliding_window_native/q_001/workspace/metrics')


if __name__ == '__main__': unittest.main()
