import json
import multiprocessing as mp
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_bc_campaign_v3 as campaign
from run_bc_trial_v3 import native_command


def concurrent_claim(root,job,queue,cap):
    value=campaign.acquire_claim(Path(root),job,{**campaign.identity(),'controller_id':'fixture'},cap)
    queue.put(value is not None)


class CampaignV3Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.job={'job_id':'dsh/visual/q_001_r01','harness':'dsh','strategy':'visual'}
    def tearDown(self):self.tmp.cleanup()

    def test_atomic_cross_process_claim_allows_exactly_one_worker(self):
        ctx=mp.get_context('fork');queue=ctx.Queue()
        workers=[ctx.Process(target=concurrent_claim,args=(str(self.root),self.job,queue,32)) for _ in range(8)]
        for worker in workers:worker.start()
        outcomes=[queue.get(timeout=10) for _ in workers]
        for worker in workers:worker.join(10);self.assertEqual(worker.exitcode,0)
        self.assertEqual(sum(outcomes),1)
        self.assertEqual(len(list((self.root/'cells/dsh/visual/slots').iterdir())),1)

    def test_cell_slots_bound_independent_jobs_and_do_not_limit_other_cell(self):
        claimed=[]
        for n in range(3):
            job={**self.job,'job_id':f'dsh/visual/q_{n}_r01'}
            claimed.append(campaign.acquire_claim(self.root,job,campaign.identity(),cap=2))
        self.assertIsNotNone(claimed[0]);self.assertIsNotNone(claimed[1]);self.assertIsNone(claimed[2])
        self.assertIsNotNone(campaign.acquire_claim(self.root,{'job_id':'hermes/visual/q_0_r01','harness':'hermes','strategy':'visual'},campaign.identity(),cap=2))

    def test_unknown_terminal_and_interrupted_are_never_claimed_again(self):
        jobdir,slot=campaign.acquire_claim(self.root,self.job,campaign.identity())
        self.assertEqual(campaign.job_state(jobdir),'unknown')
        self.assertIsNone(campaign.acquire_claim(self.root,self.job,campaign.identity()))
        attempt=jobdir/'attempts/attempt_001';attempt.mkdir(parents=True)
        for status in ('completed','failed','timeout','interrupted'):
            campaign.atomic(attempt/'result.json',{'status':status})
            self.assertEqual(campaign.job_state(jobdir),'terminal')
            self.assertIsNone(campaign.acquire_claim(self.root,self.job,campaign.identity()))
        campaign.release_slot(slot)
        self.assertIsNone(campaign.acquire_claim(self.root,self.job,campaign.identity()))

    def test_foreign_host_pid_is_never_checked_as_local(self):
        owner={**campaign.identity(),'hostname':'another-host'}
        with patch.object(campaign,'identity',return_value=campaign.identity()) as local:
            self.assertIsNone(campaign.owner_alive(owner))
            self.assertEqual(local.call_count,1)  # Read self identity only, never foreign PID.

    def test_scientific_plan_remains_3000_when_dispatch_selects_two_visual_jobs(self):
        rows=[{'id':f'q_{n:03}','question':f'Question {n}','answer':'DO NOT SEND'} for n in range(100)]
        cfg={'model':'route','bc100_campaign':{'questions':100,'repeats':3,'strategies':list(campaign.STRATEGIES),
          'models':{'dsh':'route','hermes':'route'},'timeout_seconds':1800}}
        jobs=campaign.make_jobs(rows,cfg);self.assertEqual(len(jobs),3000)
        selected=[j for j in jobs if j['strategy']=='visual'][:2]
        self.assertEqual({j['harness'] for j in selected},{'hermes','dsh'})
        self.assertEqual({j['question_id'] for j in selected},{'q_000'})
        self.assertTrue(all('answer' not in j for j in jobs))
        self.assertEqual(len({j['job_id'] for j in jobs}),3000)

    def test_native_worker_commands_are_versioned_and_map_strategy(self):
        spec={**self.job,'_spec_path':'/fixture/spec.json','question_id':'q_001','repeat':2,
          'config_path':'/fixture/frozen.json','campaign_root':'/fixture/campaign','cohort_sha256':'a'*64,'timeout_seconds':1800}
        cmd,path,timeout=native_command(spec,self.root)
        self.assertIn('run_dsh_eval_v3.py',' '.join(cmd));self.assertIn('visual_native',cmd);self.assertIn('--cohort-file',cmd);self.assertIn('/fixture/campaign/cohort.jsonl',cmd);self.assertIn('a'*64,cmd)
        self.assertEqual(path,self.root/'native/visual_native/q_001/result.json')
        self.assertEqual(timeout,2040)
        spec['harness']='hermes';cmd,path,timeout=native_command(spec,self.root)
        self.assertIn('hermes_bc_worker_v3.py',' '.join(cmd));self.assertEqual(timeout,1800)

    def test_trial_wraps_native_result_preserves_artifacts_and_releases_slot(self):
        import run_bc_trial_v3 as trial
        spec={**self.job,'question_id':'q_001','repeat':1,'model':'fixture','timeout_seconds':10,
          'config_path':'unused','slot_path':str(self.root/'slot')}
        slot=Path(spec['slot_path']);slot.mkdir();(slot/'owner.json').write_text('{}')
        out=self.root/'attempt';out.mkdir();native=out/'native/native-result.json'
        script=self.root/'native_fixture.py'
        script.write_text('import json,os\nfrom pathlib import Path\np=Path('+repr(str(native))+')\np.parent.mkdir(parents=True,exist_ok=True)\np.write_text(json.dumps({"status":"completed","final":{"text":"LOCAL-FIXTURE"},"threads":os.environ.get("OMP_NUM_THREADS")}))\n')
        source=self.root/'spec.json';source.write_text(json.dumps(spec))
        with patch.object(sys,'argv',['trial','--spec',str(source),'--out',str(out),'--live']), \
             patch.object(trial,'validate_spec'), \
             patch.object(trial,'environment',return_value=({'PATH':'/usr/bin:/bin'},{})), \
             patch.object(trial,'native_command',return_value=([sys.executable,str(script)],native,10)), \
             patch('review_execution.enforce'):
            trial.main()
        result=json.loads((out/'result.json').read_text())
        self.assertEqual(result['status'],'completed');self.assertEqual(result['final']['text'],'LOCAL-FIXTURE')
        self.assertEqual(json.loads(native.read_text())['threads'],'1')
        self.assertFalse(slot.exists());self.assertTrue((out/'heartbeat.json').exists())
        self.assertEqual(result['native_result_path'],str(native))

    def test_subreaper_detects_and_stops_setsid_child_after_launcher_exits(self):
        import run_bc_trial_v3 as trial
        spec={**self.job,'question_id':'q_001','repeat':1,'model':'fixture','timeout_seconds':10,
          'config_path':'unused','slot_path':str(self.root/'orphan-slot')}
        slot=Path(spec['slot_path']);slot.mkdir();(slot/'owner.json').write_text('{}')
        out=self.root/'orphan-attempt';out.mkdir();native=out/'native/native-result.json'
        pid_file=self.root/'orphan.pid';script=self.root/'orphan_fixture.py'
        script.write_text('import json,os,time\nfrom pathlib import Path\np=Path('+repr(str(native))+')\np.parent.mkdir(parents=True,exist_ok=True)\np.write_text(json.dumps({"status":"completed","final":{"text":"FIXTURE"}}))\npid=os.fork()\nif pid==0:\n os.setsid()\n Path('+repr(str(pid_file))+').write_text(str(os.getpid()))\n time.sleep(60)\n os._exit(0)\nos._exit(0)\n')
        source=self.root/'orphan-spec.json';source.write_text(json.dumps(spec))
        with patch.object(sys,'argv',['trial','--spec',str(source),'--out',str(out),'--live']), \
             patch.object(trial,'validate_spec'), \
             patch.object(trial,'environment',return_value=({'PATH':'/usr/bin:/bin'},{})), \
             patch.object(trial,'native_command',return_value=([sys.executable,str(script)],native,10)), \
             patch('review_execution.enforce'):
            trial.main()
        result=json.loads((out/'result.json').read_text())
        self.assertEqual(result['unconfirmed_child_termination'],[])
        self.assertTrue(result['slot_released'])
        if pid_file.exists():
            pid=int(pid_file.read_text());self.assertIsNone(campaign.identity(pid)['start_identity'])
            import os
            try:os.waitpid(pid,0)
            except ChildProcessError:pass


if __name__=='__main__':unittest.main()
