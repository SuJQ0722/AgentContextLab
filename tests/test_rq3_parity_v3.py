import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_rq3_parity_v3 as rq
import run_rq3_parity_trial as supervisor
import rq3_hermes_parity_worker as worker
import hermes_bc_worker_v3 as native
from run_bc_campaign_v3 import acquire_claim, identity, atomic


class RQ3ParityTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)/'base';self.base.mkdir();self.root=Path(self.tmp.name)/'rq3'
        cfg=json.loads((rq.BASE/'experiment.json').read_text());(self.base/'experiment.json').write_text(json.dumps(cfg));(self.base/'plan.json').write_text('{}')
        (self.base/'cohort.jsonl').write_text(''.join(json.dumps({'id':f'q_{i:03}','question':f'Question {i}','answer':'SECRET'})+'\n' for i in range(100)))
        self.patchbase=patch.object(rq,'BASE',self.base);self.patchbase.start();self.addCleanup(self.patchbase.stop)
        self.patchsources=patch.object(rq,'sources',return_value={});self.patchsources.start();self.addCleanup(self.patchsources.stop)

    def test_full_paired_plan_changes_only_far_history_scale(self):
        plan=rq.prepare(self.root);self.assertEqual(len(plan['jobs']),2100)
        for scale in rq.SCALES:
            jobs=[j for j in plan['jobs'] if j['scale']==scale];self.assertEqual(len(jobs),300)
            self.assertEqual({j['repeat'] for j in jobs},{1,2,3});self.assertEqual({j['model'] for j in jobs},{rq.MODEL})
            self.assertFalse(any('answer' in j or 'external_job_dir' in j for j in jobs))
        configs=[json.loads((self.root/'configs'/(rq.label(s)+'.json')).read_text()) for s in rq.SCALES]
        canonical=[]
        for cfg in configs:
            cfg.pop('rq3');cfg['visual_renderer'].pop('history_scale');canonical.append(cfg)
        self.assertTrue(all(c==canonical[0] for c in canonical))
        self.assertEqual(rq.prepare(self.root),plan)

    def test_claim_unknown_is_never_pending_and_frozen_scale_is_enforced(self):
        plan=rq.prepare(self.root);job=plan['jobs'][0];owner={**identity(),'controller_id':'fixture'}
        directory,slot=acquire_claim(self.root,job,owner,cap=16);attempt=directory/'attempts/attempt_001';attempt.mkdir(parents=True)
        spec={**job,'campaign_root':str(self.root),'plan_sha256':rq.sha(self.root/'plan.json'),'cohort_sha256':plan['definition']['cohort_sha256'],
              'slot_path':str(slot),'controller_id':'fixture'}
        self.assertEqual(rq.state(self.root,job),'claimed_unknown');rq.validate_trial(spec,attempt)
        original=json.loads((directory/'claim/owner.json').read_text())
        altered=dict(original,slot='/wrong');atomic(directory/'claim/owner.json',altered)
        with self.assertRaisesRegex(ValueError,'claim slot'):rq.validate_trial(spec,attempt)
        atomic(directory/'claim/owner.json',original)
        cfg=Path(spec['config_path']);value=json.loads(cfg.read_text());value['visual_renderer']['history_scale']=.333;cfg.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'input changed'):rq.validate_trial(spec,attempt)

    def test_native_guard_is_inherited_and_supervisor_is_original(self):
        self.assertIs(worker.RQ3VisionRecorder.install,native.VisionRecorder.install)
        import run_bc_trial_v3
        self.assertIs(supervisor.trial,run_bc_trial_v3)


if __name__=='__main__':unittest.main()
