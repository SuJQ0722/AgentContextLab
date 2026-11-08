import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import roll_sco_bc_v3_routes2_io3 as roll
import bootstrap_bc_v3_node_routes2_io3 as bootstrap


def put(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return path


class IO3RolloutTests(unittest.TestCase):
 def submission(self):
  name='acl-bc-v3-dsh-summarize-ops5'
  return {'name':name,'requested_at_unix':1,'argv':['sco','acp','jobs','create','--workspace-name','rl',
    '--worker-nodes','1','--worker-spec','N4lS.Iu.I80.8c32g','--job-name',name,'--name',name,
    '--container-image-url','same-private-image','--storage-mount','same-afs','--command',
    'exec python '+str(ROOT/'scripts/bootstrap_bc_v3_node_routes2.py')+' --harness dsh --strategy summarize --live']}

 def fixture(self,td):
  root=Path(td)/'campaign';repo=Path(td);name='acl-bc-v3-dsh-summarize-ops5';uid='a'*32;host='pt-'+uid+'-worker-0';bootid='boot';namespace='pid:[123]'
  jid='dsh/summarize/q_001_r01';node=root/'runtime/nodes'/(host+'-'+bootid);directory=node/'dsh-summarize';proofdir=repo/'outputs/cloud-runtime/io3-recovery/dsh-summarize'
  specpath=root/'jobs'/jid/'spec.json';out=specpath.parent/'attempts/attempt_001';out.mkdir(parents=True)
  slot=root/'cells/dsh/summarize/slots/00';identity={'hostname':host,'boot_id':bootid,'pid_namespace':namespace}
  owner={**identity,'job_id':jid,'controller_id':'old','slot':str(slot)}
  claim=put(specpath.parent/'claim/owner.json',owner);slotowner=put(slot/'owner.json',owner)
  spec={'job_id':jid,'campaign_root':str(root),'controller_id':'old','slot_path':str(slot)};put(specpath,spec)
  plan={'jobs':[{'job_id':jid,'harness':'dsh','strategy':'summarize'}]};put(root/'plan.json',plan);put(root/'route-plan-v2.json',{'immutable':'routeplan'})
  description={'name':name,'workspace_name':'rl','state':'FAILED','uid':uid};describe=put(proofdir/'describe.json',description)
  boot=put(directory/'bootstrap.json',{**identity,'cell':'dsh/summarize','started_at_unix':10})
  exited=put(directory/'exit.json',{'controller_exit_code':1,'finished_at_unix':20})
  inventory=put(proofdir/'inventory.json',{'cell':'dsh/summarize','claims':[{'job_id':jid,'candidate_unstarted':True,'forbidden_present':[]}]})
  proof={'schema':'acp-terminated-namespace-v1','platform_state':'FAILED','namespace_terminated':True,'name':name,'uid':uid,**identity,'observed_at_unix':30}
  for k,p in [('describe',describe),('bootstrap',boot),('exit',exited),('inventory',inventory)]:proof.update({k+'_path':str(p),k+'_sha256':roll.sha(p)})
  proofpath=put(proofdir/'terminated-namespace.json',proof)
  authorization=put(proofdir/'recovery-authorization.json',{'version':'bc-v3-never-started-recovery-batch-v1',
    'terminated_namespace_evidence_path':str(proofpath),'terminated_namespace_evidence_sha256':roll.sha(proofpath),
    'entries':[{'job_id':jid,'attempt_path':str(out),'spec_sha256':roll.sha(specpath),'claim_owner_sha256':roll.sha(claim),'slot_owner_sha256':roll.sha(slotowner)}]})
  manifest=put(proofdir/'recovery-manifest.json',{'version':'bc-v3-unstarted-recovery-manifest-io3','campaign_root':str(root),
    'plan_sha256':roll.sha(root/'plan.json'),'route_plan_sha256':roll.sha(root/'route-plan-v2.json'),
    'entries':[{'job_id':jid,'spec_path':str(specpath),'attempt_path':str(out),'authorization_path':str(authorization),'authorization_sha256':roll.sha(authorization)}]})
  job={'name':name,'new_name':name[:-1]+'6','harness':'dsh','strategy':'summarize','submission':self.submission()}
  return SimpleNamespace(repo=repo,root=root,job=job,plan=plan,description=description,proofpath=proofpath,proof=proof,
    boot=boot,exited=exited,inventory=inventory,manifest=manifest,authorization=authorization,out=out,claim=claim)

 def assess(self,f):
  with patch.object(roll,'ROOT',f.repo):return roll.assess_failed(f.root,f.plan,f.job,f.description)

 def test_failed_chain_real_authorization_passes_and_started_attempt_rejected(self):
  with tempfile.TemporaryDirectory() as td:
   f=self.fixture(td);self.assertTrue(self.assess(f)['eligible'])
   for name in ('worker-started.json','command.json','native'):
    p=f.out/name;p.mkdir() if name=='native' else p.write_text('{}')
    with self.assertRaises(ValueError):self.assess(f)
    p.rmdir() if name=='native' else p.unlink()

 def test_missing_or_edited_artifacts_and_empty_manifest_fail_closed(self):
  for kind in ('describe','bootstrap','exit','inventory','manifest','authorization'):
   with self.subTest(kind=kind),tempfile.TemporaryDirectory() as td:
    f=self.fixture(td)
    p=f.manifest if kind=='manifest' else f.authorization if kind=='authorization' else Path(f.proof[kind+'_path'])
    p.write_text('{}')
    with self.assertRaises((ValueError,KeyError)):self.assess(f)

 def test_cross_cell_exit_rejected_even_if_rehashed(self):
  with tempfile.TemporaryDirectory() as td:
   f=self.fixture(td);other=put(f.exited.parent.parent/'dsh-none/exit.json',json.loads(f.exited.read_text()))
   f.proof.update(exit_path=str(other),exit_sha256=roll.sha(other));put(f.proofpath,f.proof)
   with self.assertRaisesRegex(ValueError,'submitted cell'):self.assess(f)

 def test_wrong_cell_bootstrap_or_older_submission_rejected(self):
  for mode in ('cell','older'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
    f=self.fixture(td);boot=json.loads(f.boot.read_text());boot['cell']='dsh/none' if mode=='cell' else 'dsh/summarize'
    if mode=='older':boot['started_at_unix']=0
    put(f.boot,boot);f.proof['bootstrap_sha256']=roll.sha(f.boot);put(f.proofpath,f.proof)
    with self.assertRaisesRegex(ValueError,'submitted cell'):self.assess(f)

 def test_inventory_owner_namespace_and_manifest_route_sha_are_bound(self):
  for mode in ('owner','route','duplicate'):
   with self.subTest(mode=mode),tempfile.TemporaryDirectory() as td:
    f=self.fixture(td)
    if mode=='owner':
     owner=json.loads(f.claim.read_text());owner['pid_namespace']='pid:[wrong]';put(f.claim,owner)
    else:
     m=json.loads(f.manifest.read_text())
     if mode=='route':m['route_plan_sha256']='0'*64
     else:m['entries']*=2
     put(f.manifest,m)
    with self.assertRaises(ValueError):self.assess(f)

 def test_only_exact_names_and_bootstrap_change_resources_are_preserved(self):
  old=self.submission();before=copy.deepcopy(old);argv=roll.create_argv(old,'acl-bc-v3-dsh-summarize-ops6')
  self.assertEqual([i for i,(x,y) in enumerate(zip(old['argv'],argv)) if x!=y],[old['argv'].index(k)+1 for k in ('--job-name','--name','--command')]);self.assertEqual(old,before)
  self.assertEqual(argv[argv.index('--container-image-url')+1],'same-private-image');self.assertEqual(argv[argv.index('--storage-mount')+1],'same-afs')
  self.assertIn('bootstrap_bc_v3_node_routes2_io3.py',argv[-1])
  with self.assertRaises(ValueError):roll.create_argv(old,'acl-bc-v3-hermes-summarize-ops6')
  old['argv']+=['--name',old['name']]
  with self.assertRaises(ValueError):roll.create_argv(old,'acl-bc-v3-dsh-summarize-ops6')

 def test_bootstrap_uses_only_explicit_io3_controller_and_manifest(self):
  with tempfile.TemporaryDirectory() as td,patch.object(bootstrap,'ROOT',Path(td)):
   args=SimpleNamespace(root=Path(td)/'campaign',harness='dsh',strategy='summarize',reader_python='python',controller_concurrency=16)
   cmd=bootstrap.commands(args)['controller'];self.assertTrue(cmd[1].endswith('run_bc_campaign_v3_routes2_io3.py'));self.assertNotIn('--unstarted-recovery-manifest',cmd)
   manifest=put(Path(td)/'outputs/cloud-runtime/io3-recovery/dsh-summarize/recovery-manifest.json',{})
   cmd=bootstrap.commands(args)['controller'];self.assertEqual(cmd[cmd.index('--unstarted-recovery-manifest')+1],str(manifest))
   self.assertEqual(cmd[cmd.index('--concurrency')+1],'16')

 def test_succeeded_cycle_keeps_original_clean_drain_assessor(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);put(root/'plan.json',{'jobs':[]});cfg=put(root/'dispatch.json',{'active_workers_per_cloud_instance':16,'local_target_workers':2})
   args=SimpleNamespace(root=root,dispatch_config=cfg,parent_generation='ops5',generation='ops6',live=False,
    harness=['dsh'],strategy=['summarize'],receipts=root/'receipts',submissions=root/'submissions',sco=Path('sco'))
   description={'state':'SUCCEEDED'};job={'name':'old','new_name':'new'}
   with patch.object(roll,'RoutePlan'),patch.object(roll,'parent_job',return_value=job),patch.object(roll.parent,'assess',return_value={'eligible':False,'reason':'drain unproven'}) as assess,patch.object(roll,'assess_failed') as failed:
    result=roll.cycle(args,query=Mock(return_value={'returncode':0,'stdout':json.dumps(description)}))
   assess.assert_called_once();failed.assert_not_called();self.assertFalse(result['jobs'][0]['eligible'])

if __name__=='__main__':unittest.main()
