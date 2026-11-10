import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_bc_bounded_retry_v1 as controller
import run_bc_bounded_retry_trial_v1 as trial
from hermes_bounded_bc_worker_v1 import validate_bc


def job(h,i):
    return {'job_id':f'{h}/visual/q_{i:03}_r01','harness':h,'strategy':'visual',
        'question_id':f'q_{i:03}','repeat':1,'bounded_bc_protocol':'bc-bounded-pages-v1',
        'scale':.75,'scale_key':'scale_0750','config_path':'/frozen/experiment.json',
        'cohort_sha256':'cohort','campaign_root':'/frozen','timeout_seconds':1800,
        '_spec_path':'/frozen/spec.json'}


class BCBoundedTests(unittest.TestCase):
    def test_disjoint_harness_cells_and_duplicates_rejected(self):
        p={'definition':{'harnesses':['hermes','dsh'],'per_cell_concurrency_cap':16},
           'jobs':[job('hermes',1),job('dsh',1)]}
        self.assertEqual([len(controller.selected_jobs(p,h)) for h in ('hermes','dsh')],[1,1])
        with self.assertRaises(ValueError):controller.selected_jobs(p,'unknown')
        p['jobs'].append(job('hermes',1))
        with self.assertRaises(ValueError):controller.selected_jobs(p,'hermes')

    def test_each_harness_has_only16_slots_claims_are_not_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p={'definition':{'cohort_sha256':'cohort'}}
            (root/'plan.json').write_text('{}');owner={'controller_id':'owner'}
            claims=[]
            for h in ('hermes','dsh'):
                claims.extend(controller.publish_spec(root,job(h,i),owner,p) for i in range(17))
            self.assertEqual(sum(c is not None for c in claims),32)
            self.assertIsNone(controller.publish_spec(root,job('hermes',0),owner,p))
            controller.release_slot(claims[0][1])
            self.assertIsNone(controller.publish_spec(root,job('hermes',0),owner,p))
            self.assertIsNotNone(controller.publish_spec(root,job('hermes',16),owner,p))

    def test_trial_uses_exact_native_wrappers_and_result_paths(self):
        out=Path('/independent/attempt')
        c,p,t=trial.native_command(job('hermes',1),out)
        self.assertTrue(c[1].endswith('hermes_bounded_bc_worker_v1.py'));self.assertEqual(t,1800)
        self.assertEqual(p,out/'native/native-result.json')
        c,p,t=trial.native_command(job('dsh',1),out)
        self.assertTrue(c[1].endswith('dsh_bounded_bc_worker_v1.py'));self.assertEqual(t,2040)
        self.assertEqual(p,out/'native/visual_native/q_001/result.json')
        with self.assertRaises(ValueError):trial.native_command(dict(job('dsh',1),strategy='none'),out)

    def test_hermes_requires_bc_protocol_and_exact075_scale(self):
        with patch('hermes_bounded_bc_worker_v1.validate_rq3') as validate:
            spec=job('hermes',1);cfg={'bounded_bc_protocol':'bc-bounded-pages-v1'}
            validate_bc(spec,cfg,Path('/fresh'))
            self.assertEqual(validate.call_args.args[0]['bounded_rq3_protocol'],'rq3-bounded-pages-v1')
            self.assertNotIn('bounded_rq3_protocol',spec)
            with self.assertRaises(ValueError):validate_bc(dict(spec,scale=.5),cfg,Path('/fresh'))
            with self.assertRaises(ValueError):validate_bc(spec,{},Path('/fresh'))

if __name__=='__main__':unittest.main()
