import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import repool_visual_inline_toolcall_v7 as m

class MigrationTests(unittest.TestCase):
 def setUp(self):
  x=patch.object(m,'load_validate',return_value=({},{}));x.start();self.addCleanup(x.stop)
 def test_scope_and_execution_evidence_fail_closed(self):
  with self.assertRaises(ValueError):m.app_name('mmbc_vera')
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);m.no_execution(root)
   p=root/'jobs/hermes/visual/q/claim/owner.json';p.parent.mkdir(parents=True);p.write_text('{}')
   with self.assertRaisesRegex(ValueError,'Execution evidence'):m.no_execution(root)
 def setup_record(self,tmp):
  root=Path(tmp)/'root';root.mkdir();(root/'plan.json').write_text('{}');d=Path(tmp)/'deployment';d.mkdir();cfg=d/'config.yaml';cfg.write_text('{}')
  return {'root':str(root),'config_path':str(cfg),'old_config_path':str(cfg),'old_config_sha256':m.sha(cfg),'name':'new','migration_source_sha256':m.sha(m.__file__),'plan_sha256':m.sha(root/'plan.json'),'old_name':'old','old_uid':'uid','launch_marker':str(d/'marker.json'),'config_sha256':m.sha(cfg)}
 def test_post_stop_claim_forbids_create(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=self.setup_record(tmp);root=Path(r['root'])
   def stop(argv):
    p=root/'jobs/hermes/visual/q/claim/owner.json';p.parent.mkdir(parents=True);p.write_text('{}');return {'returncode':0}
   with patch.object(m,'fresh',side_effect=[{'state':'PROGRESSING','ready_replicas':0},{'state':'PROGRESSING','ready_replicas':0},{'state':'SUSPENDED','ready_replicas':0}]),patch.object(m.cli,'create_cli',side_effect=stop),patch.object(m.cli,'submit') as submit:
    with self.assertRaisesRegex(ValueError,'Execution evidence'):m.migrate(r)
    submit.assert_not_called()
 def test_unknown_stop_never_creates_or_replays(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=self.setup_record(tmp)
   with patch.object(m,'fresh',return_value={'state':'PROGRESSING','ready_replicas':0}),patch.object(m.cli,'create_cli',return_value={'returncode':None}),patch.object(m.cli,'submit') as submit:
    with self.assertRaisesRegex(ValueError,'stop unconfirmed'):m.migrate(r)
    with self.assertRaisesRegex(ValueError,'already attempted'):m.migrate(r)
    submit.assert_not_called()
 def test_same_uid_stop_proof_precedes_creation(self):
  with tempfile.TemporaryDirectory() as tmp:
   r=self.setup_record(tmp);root=Path(r['root'])
   def create(record):
    self.assertFalse((root/'STOP').exists());self.assertTrue((Path(r['config_path']).parent/'old-stopped-proof.json').exists());return {'state':'submitted'}
   with patch.object(m,'fresh',side_effect=[{'state':'PROGRESSING','ready_replicas':0},{'state':'PROGRESSING','ready_replicas':0},{'state':'SUSPENDED','ready_replicas':0}]),patch.object(m.cli,'create_cli',return_value={'returncode':0}),patch.object(m.cli,'submit',side_effect=create),patch.object(m.cli,'describe',return_value={'returncode':0,'stdout':json.dumps({'name':'new','uid':'newuid'})}),patch.object(m,'config_matches'):
    m.migrate(r)
    self.assertTrue(Path(r['launch_marker']).exists())

 def test_platform_sidecar_or_env_change_rejected(self):
  cfg={'template':{'containers':[{'command':['x'],'image_path':'i','resource_request':{'cpu':'8'},'env':[],'volume_mounts':[]}]},'resource_pool':{'name':'dev-infra'}}
  m.config_matches(cfg,cfg)
  import copy
  actual=copy.deepcopy(cfg);actual['template']['containers'].append(copy.deepcopy(actual['template']['containers'][0]))
  with self.assertRaisesRegex(ValueError,'sidecar'):m.config_matches(actual,cfg)
  actual=copy.deepcopy(cfg);actual['template']['containers'][0]['env']=[{'name':'X','value':'Y'}]
  with self.assertRaisesRegex(ValueError,'env'):m.config_matches(actual,cfg)

if __name__=='__main__':unittest.main()
