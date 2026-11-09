import importlib,io,json,os,signal,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import bootstrap_rq3_scale_ops2 as boot

class BootstrapTests(unittest.TestCase):
 def test_commands_use_only_selected_rq3_controller_and_host_preflight(self):
  args=SimpleNamespace(root=Path('/tmp/rq3'),scale='scale_0125',reader_python='/opt/conda/bin/python')
  c=boot.commands(args)
  self.assertIn('run_rq3_scale_cloud_ops2.py',Path(c['controller'][1]).name)
  self.assertEqual(c['controller'][-4:],['--concurrency','16','--resume','--live'])
  self.assertEqual(c['controller'][c['controller'].index('--scale')+1],'scale_0125')
  self.assertIn(str(args.root/'experiment.json'),c['web_preflight'])
  self.assertEqual(c['reader'][0],'/opt/conda/bin/python')
  self.assertIn('--telemetry-watch',c['telemetry'])
 def test_dry_mode_cannot_start_services_or_validate_core(self):
  output=io.StringIO()
  with patch.object(sys,'argv',['bootstrap','--scale','.125','--dry']),patch.object(boot,'normalize_scale',return_value='scale_0125'),patch.object(boot,'scientific_validation',side_effect=AssertionError('dry validation forbidden')),patch.object(boot,'runtime_snapshot',side_effect=AssertionError('dry runtime command forbidden')),patch.object(boot,'serve',side_effect=AssertionError('dry live service forbidden')),patch.object(sys,'stdout',output):
   boot.main()
  plan=json.loads(output.getvalue());self.assertEqual(plan['mode'],'dry_run');self.assertEqual(plan['required_cloud_allocation']['workers'],16)
 def test_credentials_scrubbed_proxy_allowed_loopback_forced(self):
  e=boot.research_environment({'PATH':'/bin','SCO_TOKEN':'secret','AWS_SECRET_ACCESS_KEY':'secret','SSH_AUTH_SOCK':'secret','TOKENHUB_API_KEY':'do-not-inherit'},
      {'https_proxy':'http://internal-proxy:8080','SCO_AK':'secret','NO_PROXY':'existing'})
  for key in ['SCO_TOKEN','AWS_SECRET_ACCESS_KEY','SSH_AUTH_SOCK','TOKENHUB_API_KEY','SCO_AK']:self.assertNotIn(key,e)
  self.assertEqual(e['https_proxy'],'http://internal-proxy:8080');self.assertIn('127.0.0.1',e['no_proxy'])
 def test_only_rq3_validator_called(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);plan={'definition':{'version':'rq3-test'},'jobs':[]};(root/'plan.json').write_text(json.dumps(plan))
   with patch('run_rq3_parity_v3.validate') as validate,patch('run_bc_campaign_v3.validate_sources',side_effect=AssertionError('core validation forbidden')):
    self.assertEqual(boot.scientific_validation(root),plan);validate.assert_called_once_with(plan,root)
 def test_reader_failure_drains_controller_before_reader_shutdown(self):
  events=[]
  class Child:
   def __init__(self,name):self.name=name;self.pid={'reader':111,'telemetry':112,'controller':113}[name];self.returncode=None;self.stopping=False;self.polls=0
   def poll(self):
    if self.name=='controller' and self.stopping:
     self.polls+=1
     if self.polls>=2:self.returncode=0;events.append('controller_drained')
    return self.returncode
   def send_signal(self,sig):events.append(self.name+'_signal');self.stopping=True
   def terminate(self):self.returncode=0;events.append(self.name+'_terminate')
   def kill(self):self.returncode=-9
   def wait(self,timeout=None):events.append(self.name+'_wait');self.returncode=0
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);local=root/'local';local.mkdir();args=SimpleNamespace(root=root,scale='scale_0125')
   children={name:Child(name) for name in ['reader','telemetry','controller']}
   plan={'hostname':'host','boot_id':'boot','runtime':{'reader_source_sha256':'expected'},'commands':{**{n:[n] for n in children},'web_preflight':['preflight']}}
   times=iter(range(0,1000,20))
   with patch.object(boot.subprocess,'Popen',side_effect=lambda cmd,**kw:children[cmd[0]]),patch.object(boot,'checked'),patch.object(boot,'health',side_effect=[False,True,False]),patch.object(boot.signal,'signal'),patch.object(boot.time,'monotonic',side_effect=lambda:next(times)),patch.object(boot.time,'sleep'),patch.object(boot.os,'killpg',side_effect=lambda pid,sig:events.append('reader_killpg')):
    self.assertEqual(boot.serve(args,plan,{},local),0)
   self.assertLess(events.index('controller_signal'),events.index('controller_drained'))
   self.assertLess(events.index('controller_drained'),events.index('reader_killpg'))
   exit=json.loads((root/'runtime/nodes/host-boot/scale_0125/exit.json').read_text());self.assertTrue(exit['stop_dispatch_requested']);self.assertFalse(exit['native_processes_signaled'])

if __name__=='__main__':unittest.main()
