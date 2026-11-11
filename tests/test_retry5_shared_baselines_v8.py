"""Mixed baseline queue shares sixteen physical slots and preserves native strategy."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_visual_inline_retry5_v8 as controller
import run_visual_inline_retry5_trial_v8 as trial
from one_hour_timeout_retry_v1 import VERSION
from inline_route_contract_v2 import ROUTES
from run_bc_campaign_v3 import release_slot

class SharedBaselineTests(unittest.TestCase):
    def jobs(self):
        return [{'job_id':f'{h}/{s}/q_{i:03d}_r01','harness':h,'strategy':s,'question_id':f'q_{i:03d}','repeat':1}
                for i in range(24) for h,s in [('hermes' if i%2 else 'dsh',('none','discard','summarize','sliding_window')[i%4])]]
    def test_mixed_queue_has_one_controller_identity(self):
        jobs=self.jobs();plan={'definition':{'one_hour_retry_version':VERSION,'container_group':'shared_baselines'},'jobs':jobs}
        self.assertEqual(controller.selected_jobs(plan,'hermes'),jobs)
        with self.assertRaisesRegex(ValueError,'single controller'):controller.selected_jobs(plan,'dsh')
    def test_sixteen_total_slots_across_harnesses_and_strategies_including_unknown_claims(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);jobs=self.jobs();plan={'definition':{'cohort_sha256':'fixture'},'jobs':jobs}
            (root/'plan.json').write_text(json.dumps(plan));owner={'controller_id':'owner'}
            reservations=[controller.publish_spec(root,j,owner,plan) for j in jobs[:16]]
            self.assertTrue(all(reservations));slots=[x[1] for x in reservations]
            self.assertEqual(len(set(slots)),16)
            self.assertEqual({p.parent for p in slots},{root/'cells/shared/all/slots'})
            self.assertIsNone(controller.publish_spec(root,jobs[16],{'controller_id':'restart'},plan))
            # Unknown old work reserves its slot; a restart does not create a new harness-specific pool.
            self.assertIsNone(controller.publish_spec(root,jobs[0],{'controller_id':'restart'},plan))
            release_slot(slots[0]);self.assertIsNotNone(controller.publish_spec(root,jobs[16],owner,plan))
            self.assertEqual(len(list((root/'cells/shared/all/slots').iterdir())),16)
            for job,reservation in zip(jobs,reservations):
                self.assertEqual(reservation[3]['harness'],job['harness'])
                self.assertEqual(reservation[3]['strategy'],job['strategy'])
    def test_native_baseline_commands_keep_strategy_cohort_and_one_hour(self):
        contract={'one_hour_retry_version':VERSION,'timeout_seconds':3600,'max_timeout_retries':5,
            'max_output_tokens':8192,'model':ROUTES[0],'model_route_policy':'four-route-rotation-v1',
            'approved_model_routes':ROUTES,'image_transport':'inline-recent-ten-chunked-v1',
            'transport_delivery_version':'inline-direct-v1','transport_runtime_version':'visual-transport-runtime-v4',
            'gateway_proxy':'http://10.120.0.246:7890'}
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);config=root/'config.json';config.write_text(json.dumps(contract))
            for harness in ('hermes','dsh'):
                for strategy in ('none','discard','summarize','sliding_window'):
                    spec={**contract,'harness':harness,'strategy':strategy,'question_id':'q','repeat':2,
                        'config_path':str(config),'campaign_root':str(root),'_spec_path':str(root/'spec.json'),
                        'cohort_sha256':'public','native_cohort_path':str(root/'native-cohort.jsonl'),'native_cohort_sha256':'native'}
                    command,result,deadline=trial.native_command(spec,root/'attempt')
                    self.assertEqual(deadline,3600)
                    self.assertTrue(command[1].endswith(f'{harness}_baseline_inline_worker_v8.py'))
                    if harness=='dsh':
                        expected='sliding_window_native' if strategy=='sliding_window' else strategy
                        self.assertEqual(command[command.index('--strategies')+1],expected)
                        self.assertEqual(command[command.index('--timeout')+1],'3600')
                        self.assertEqual(command[command.index('--cohort-sha256')+1],'native')
                        self.assertEqual(command[command.index('--config')+1],str(config))

    def test_controlled_text_waits_without_slot_then_records_blocked_without_api(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'control-targets/ref.json';reference=root/'visual-jobs/ref'
            job={**self.jobs()[0],'controlled_dependency':str(target),'controlled_reference_job_path':str(reference)}
            plan={'definition':{'cohort_sha256':'fixture'},'jobs':[job]};(root/'plan.json').write_text(json.dumps(plan))
            self.assertIsNone(controller.publish_spec(root,job,{'controller_id':'owner'},plan))
            self.assertFalse((root/'jobs'/job['job_id']/'claim').exists())
            terminal=reference/'attempts/attempt_001/result.json';terminal.parent.mkdir(parents=True)
            terminal.write_text(json.dumps({'status':'timeout','slot_released':True,'unconfirmed_child_termination':[]}))
            self.assertIsNone(controller.publish_spec(root,job,{'controller_id':'owner'},plan))
            blocked=json.loads((root/'jobs'/job['job_id']/'attempts/attempt_001/result.json').read_text())
            self.assertEqual(blocked['status'],'blocked');self.assertEqual(blocked['api_calls'],0)
            self.assertTrue(blocked['slot_released']);self.assertEqual(blocked['reference_sha256'],controller.digest(terminal.read_bytes()))
            self.assertEqual(list((root/'cells/shared/all/slots').iterdir()),[])

    def test_invalid_measured_control_target_never_dispatches_or_reserves(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);target=root/'target.json';target.write_text(json.dumps({'passed':False}))
            job={**self.jobs()[0],'controlled_dependency':str(target)}
            with self.assertRaisesRegex(ValueError,'Invalid measured'):
                controller.publish_spec(root,job,{'controller_id':'owner'},{'jobs':[job]})
            self.assertFalse((root/'jobs').exists())
