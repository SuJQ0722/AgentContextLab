import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import run_bounded_vera_retry_v1 as run
import run_bounded_vera_trial_v1 as trial


def job(index,shard=0):
    return {'job_id':f'hermes/visual/q_{index:03}_r01','harness':'hermes','strategy':'visual',
            'shard':shard,'question_id':f'q_{index:03}','repeat':1,'model':'test','question':'public question',
            'timeout_seconds':1800,'bounded_visual_protocol':'bounded-multimodal-pages-v1'}


def plan(jobs):
    return {'definition':{'shards':3,'per_cell_concurrency_cap':48,'cohort_sha256':'test'},'jobs':jobs}


class RetryTests(unittest.TestCase):
    def test_shards_partition_only_selected_subset(self):
        jobs=[job(i,i%3) for i in range(26,300)]
        p=plan(jobs);groups=[run.selected_jobs(p,i) for i in range(3)]
        ids=[j['job_id'] for g in groups for j in g]
        self.assertEqual(len(ids),274);self.assertEqual(len(set(ids)),274)
        self.assertNotIn(job(0)['job_id'],ids)
        for invalid in (-1,3,True):
            with self.assertRaises(ValueError):run.selected_jobs(p,invalid)
        with self.assertRaises(ValueError):run.selected_jobs(plan([job(0),job(0)]),0)

    def test_claims_never_reused_and_global_cap_is48(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=plan([job(i) for i in range(49)])
            (root/'plan.json').write_text(json.dumps(p));owner={'controller_id':'owner'}
            claims=[run.publish_spec(root,j,owner,p) for j in p['jobs']]
            self.assertEqual(sum(x is not None for x in claims),48)
            self.assertIsNone(run.publish_spec(root,job(0),owner,p))
            run.release_slot(claims[0][1])
            self.assertIsNone(run.publish_spec(root,job(0),owner,p))
            self.assertIsNotNone(run.publish_spec(root,job(48),owner,p))

    def test_lease_remote_unknown_blocked_then_explicit_exit_allows_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old={'controller_id':'old','run_directory':str(root/'controllers/0/old')}
            p,lock=run.acquire_lease(root,0,old);lock.close()
            new={'controller_id':'new','run_directory':str(root/'controllers/0/new')}
            with patch.object(run,'owner_alive',return_value=None):
                with self.assertRaises(ValueError):run.acquire_lease(root,0,new)
                run.atomic(Path(old['run_directory'])/'exit.json',{'controller_id':'old','drained':True})
                _,lock=run.acquire_lease(root,0,new);lock.close()
            self.assertEqual(json.loads((p/'history/old.json').read_text()),old)

    def test_lease_holds_exclusive_lock_and_dead_local_reclaim_preserves_epoch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old={'controller_id':'old','run_directory':str(root/'controllers/0/old')}
            p,lock=run.acquire_lease(root,0,old)
            with self.assertRaises(BlockingIOError):run.acquire_lease(root,0,old)
            lock.close();new={'controller_id':'new','run_directory':str(root/'controllers/0/new')}
            with patch.object(run,'owner_alive',return_value=False):
                _,lock=run.acquire_lease(root,0,new);lock.close()
            self.assertTrue((p/'history/old.json').exists())

    def test_concurrency_and_native_entry_are_explicit(self):
        with self.assertRaises(ValueError):run.controller(Path('/unused'),0,17)
        with self.assertRaises(ValueError):run.controller(Path('/unused'),0,True)
        spec={**job(1),'_spec_path':'/tmp/public-spec.json'}
        command,result,deadline=trial.native_command(spec,Path('/tmp/new-attempt'))
        self.assertTrue(command[1].endswith('/hermes_bounded_mmbc_worker_v1.py'))
        self.assertEqual(deadline,1800)
        with self.assertRaises(ValueError):trial.native_command({**spec,'harness':'dsh'},Path('/tmp/new'))

    def test_limit_then_resume_does_not_repeat_old_paid_claims(self):
        import prepare_bounded_vera_retry_v1 as prep
        import preflight_bc_v3_web as web
        import review_execution
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);p=plan([job(i) for i in range(20)])
            (root/'plan.json').write_text(json.dumps(p));(root/'experiment.json').write_text('{}')
            launched=[];counts={'active':0,'peak':0}
            class Child:
                pid=999999999
                def __init__(self,spec,out):self.spec=spec;self.out=out;self.done=False
                def poll(self):
                    if not self.done:
                        self.done=True;counts['active']-=1
                        run.atomic(self.out/'result.json',{'status':'completed'})
                        run.release_slot(Path(self.spec['slot_path']))
                    return 0
            def popen(argv,**kwargs):
                spec=json.loads(Path(argv[argv.index('--spec')+1]).read_text());out=Path(argv[argv.index('--out')+1])
                launched.append(spec['job_id']);counts['active']+=1;counts['peak']=max(counts['peak'],counts['active']);return Child(spec,out)
            with (patch.object(prep,'load_validate',return_value=(p,{})),patch.object(prep,'validate_sources'),
                  patch.object(run,'environment',return_value=({},{})),patch.object(review_execution,'enforce'),
                  patch.object(web,'preflight',return_value={'passed':True}),patch.object(run.signal,'signal'),
                  patch.object(run.time,'sleep'),patch.object(run,'ROOT',root)):
                run.controller(root,0,16,popen=popen,limit=1)
                self.assertEqual(launched,[job(0)['job_id']])
                run.controller(root,0,16,popen=popen)
            self.assertEqual(len(launched),20);self.assertEqual(len(set(launched)),20)
            self.assertEqual(counts['peak'],16);self.assertEqual(counts['active'],0)
            exits=list((root/'controllers/0').glob('*/exit.json'))
            self.assertEqual(len(exits),2)
            self.assertTrue(all(json.loads(e.read_text())['drained'] for e in exits))


if __name__=='__main__':unittest.main()
