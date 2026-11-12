import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import provision_seven_retry3_v10 as p
class ProvisionTests(unittest.TestCase):
 def test_template_alias_is_explicit_and_fixed_resources(self):
  for pool,path in p.TEMPLATES.items():
   c=p.validated_template(path);self.assertEqual(c['resource_pool']['name'],pool)
   self.assertEqual(c['template']['containers'][0]['resource_request'],{'cpu':'8','memory':'32GiB'})
 def test_old_protocol_and_wrong_root_refused(self):
  root=p.CAMPAIGN/'cells/bc_dsh'
  with patch.object(p,'load_validate',return_value=({'definition':{'one_hour_retry_version':'visual-inline-one-hour-retry5-v8'}},{})):
   with self.assertRaises(ValueError):p.validate_root('bc_dsh',root)
  with self.assertRaises(ValueError):p.validate_root('bc_dsh',Path('/old/cell'))
 def test_prepare_is_offline_new_namespace_and_fixed16(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'campaign';receipts=Path(tmp)/'receipts';cell=root/'cells/bc_dsh';cell.mkdir(parents=True);(cell/'plan.json').write_text('{}')
   with patch.object(p,'CAMPAIGN',root),patch.object(p,'RECEIPTS',receipts),patch.object(p,'validate_root',return_value=({'definition':{}},{'harness':'dsh'})),patch.object(p.cloud,'submit') as submit:
    record=p.prepare('bc_dsh','agents');self.assertEqual(record['max_attempts'],3);self.assertEqual(record['concurrency'],16);self.assertTrue(record['name'].startswith('acl-v10s-'))
    config=p.yaml.safe_load(Path(record['config_path']).read_text());cmd=config['template']['containers'][0]['command'][-1]
    self.assertIn('bootstrap_seven_retry3_v10.py',cmd);self.assertIn('--concurrency 16',cmd);self.assertFalse(Path(record['launch_marker']).exists());submit.assert_not_called()
    other=receipts/'acl-other/request.json';other.parent.mkdir();other.write_text(json.dumps({'cell':'bc_dsh','name':'other'}))
    with self.assertRaisesRegex(ValueError,'already submitted'):p.prepare('bc_dsh','agents')
if __name__=='__main__':unittest.main()
