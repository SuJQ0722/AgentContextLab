import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import provision_inline_retry5_v8 as worker

class ProvisionRetry5Tests(unittest.TestCase):
 def fixture(self):
  return {'replicas':1,'display_name':'old','resource_pool':{'name':'agentic-rl'},'template':{'resource_spec':{'name':'N4lS.Iu.I80.8c32g'},'containers':[{'name':'worker','image_path':'registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401','resource_request':{'cpu':'8','memory':'32GiB'},'env':[],'volume_mounts':[{'id':'019ed8e0-f4f8-71f7-830c-f8a1e667a9ec','mount_path':'/mnt/afs_agents','subdir':'/'}]}]}}
 def test_actual_template_schema_and_resource_mutations(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'template.yaml';value=self.fixture();p.write_text(yaml.safe_dump(value));self.assertEqual(worker.validated_template(p),value)
   for field,new in [('resource_request',{'cpu':'16','memory':'32GiB'}),('image_path','public/other'),('volume_mounts',[])]:
    changed=copy.deepcopy(value);changed['template']['containers'][0][field]=new;p.write_text(yaml.safe_dump(changed))
    with self.assertRaises(ValueError):worker.validated_template(p)
 def test_info_loss_prepares_no_cloud_calls_and_exact_worker(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);template=root/'template.yaml';template.write_text(yaml.safe_dump(self.fixture()))
   out=root/'outputs/experiment6/inline-retry5-v8';out.mkdir(parents=True);(out/'manifest.json').write_text('{}')
   with patch.object(worker,'ROOT',root),patch.object(worker,'RECEIPTS',root/'receipts'),patch.dict(worker.TEMPLATES,{'agentic':template}),patch.object(worker,'validate_root',return_value=(None,{})),patch.object(worker.cloud,'submit',side_effect=AssertionError('dry prepare must not create')):
    record=worker.prepare('info_loss','agentic');cfg=yaml.safe_load(Path(record['config_path']).read_text());command=cfg['template']['containers'][0]['command'][2]
    self.assertIn('info_loss_inline_retry_v8.py',command);self.assertIn('--resume --live',command);self.assertEqual(record['concurrency'],16)
    self.assertFalse(Path(record['launch_marker']).exists())
