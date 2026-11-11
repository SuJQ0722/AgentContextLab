"""Freeze mixed recovery inputs and validate actual native command construction offline."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_inline_retry5_v8 as prep
import run_visual_inline_retry5_trial_v8 as trial
from one_hour_timeout_retry_v1 import validate,VERSION
from inline_route_contract_v2 import validate_routes
from visual_transport_runtime_v3 import DEFAULT_POLICY

class PrepareTests(unittest.TestCase):
    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    def fixture(self,root):
        records=[];v7=root/'v7';source=root/'source'
        for cell,benchmark,harness,strategy in [('bc_hermes','bc100','hermes','visual'),('mmbc_vera','mmbc100','hermes','visual'),('rq3_scale_0750','rq3','hermes','visual'),('other_strategies','bc100','dsh','discard')]:
            prior=source/cell;cfg={'model':prep.ROUTES[0],'max_output_tokens':8192,'timeout_seconds':7200,
                'transport_runtime_policy':DEFAULT_POLICY,'execution_version':'hermes-parity-v3',
                'bounded_bc_protocol':'bc-bounded-pages-v1','bounded_visual_protocol':'bounded-multimodal-pages-v1',
                'bounded_rq3_protocol':'rq3-bounded-pages-v1','scientific_sentinel':{'unchanged':cell}}
            self.write(prior/'experiment.json',cfg);self.write(prior/'plan.json',{'scientific_identity':cell})
            cohort=json.dumps({'id':'q_001','question':'fixture question','answer':'PRIVATE'})+'\n'
            (prior/'cohort.jsonl').write_text(cohort)
            self.write(v7/cell/'experiment.json',cfg);(v7/cell/'cohort.jsonl').write_text(cohort)
            job={'job_id':f'{harness}/{strategy}/q_001_r01','harness':harness,'strategy':strategy,'question_id':'q_001','question':'fixture question','repeat':1,'timeout_seconds':7200,'model':prep.ROUTES[0]}
            attempt=prior/'attempt';self.write(attempt/'result.json',{'status':'timeout','slot_released':True,'unconfirmed_child_termination':[]})
            records.append({'benchmark':benchmark,'cell':cell,'harness':harness,'strategy':strategy,'question_id':'q_001','repeat':1,'model':prep.ROUTES[0],
                'status':'timeout','job_id':job['job_id'],'source_job':job,'source_plan_path':str(prior/'plan.json'),'source_config_path':str(prior/'experiment.json'),'attempt':str(attempt)})
        self.write(root/'inventory.json',{'records':records});return v7,records
    def test_four_cell_freeze_preserves_science_and_builds_one_hour_native_commands(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);v7,records=self.fixture(root);destination=root/'frozen'
            originals={r['source_config_path']:Path(r['source_config_path']).read_bytes() for r in records}
            with patch.object(prep,'V7',v7),patch.object(prep,'DEST',destination),patch.object(prep,'source_hashes',return_value={}):
                manifests=prep.prepare(root/'inventory.json')
            self.assertEqual(len(manifests),4)
            for manifest in manifests:
                cell=Path(manifest['root']);plan=json.loads((cell/'plan.json').read_text());self.assertEqual(plan['definition']['maximum_new_attempts'],6)
                self.assertNotIn('PRIVATE',(cell/'cohort.jsonl').read_text())
                for job in plan['jobs']:
                    cfg=json.loads(Path(job['config_path']).read_text());validate(job,cfg);validate_routes(job,cfg)
                    self.assertEqual(cfg['scientific_sentinel']['unchanged'], 'other_strategies' if manifest['cell']=='shared_baselines' else manifest['cell'])
                    self.assertEqual(cfg['transport_runtime_policy'],DEFAULT_POLICY)
                    spec={**job,'campaign_root':str(cell),'cohort_sha256':plan['definition']['cohort_sha256'],'_spec_path':str(cell/'spec.json')}
                    command,result,deadline=trial.native_command(spec,cell/'jobs'/job['job_id']/'attempts/attempt_001/runs/attempt_001')
                    self.assertEqual(deadline,3600)
                    if job['harness']=='dsh':
                        self.assertEqual(command[command.index('--cohort-file')+1],job['native_cohort_path'])
                        self.assertEqual(command[command.index('--strategies')+1],'discard')
                    else:self.assertTrue(command[1].endswith('hermes_visual_inline_retry_worker_v4.py'))
            self.assertTrue(all(Path(p).read_bytes()==old for p,old in originals.items()))
    def test_successful_execution_is_retained_regardless_of_grade_and_inventory_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);v7,records=self.fixture(root);record=records[0]
            self.write(Path(record['attempt'])/'result.json',{'status':'completed','score':0})
            self.assertEqual(prep.selected(record),(False,'completed_retained',None))
            self.write(Path(record['attempt'])/'result.json',{'status':'timeout','slot_released':False,'unconfirmed_child_termination':[{'pid':1}]})
            with patch.object(prep,'certified_stopped',return_value=None):self.assertFalse(prep.selected(record)[0])
