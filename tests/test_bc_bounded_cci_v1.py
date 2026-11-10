import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import yaml
import bootstrap_bc_bounded_retry_v1 as boot
import provision_bc_bounded_retry_v1 as provision


class BoundedCCITests(unittest.TestCase):
    def template(self): return yaml.safe_load(provision.base.TEMPLATE.read_text())

    def test_distinct_shards_reviewed_resources_marker_and_argv(self):
        template = self.template(); old = copy.deepcopy(template)
        configs = [provision.build_config(template, i) for i in provision.HARNESSES]
        self.assertEqual(template, old)
        self.assertEqual(len({c['display_name'] for c in configs}), 2)
        for i, c in enumerate(configs):
            x = c['template']['containers'][0]
            self.assertEqual(x['resource_request'], {'cpu':'8','memory':'32GiB'})
            self.assertEqual(x['volume_mounts'][0]['id'], '019ed8e0-f4f8-71f7-830c-f8a1e667a9ec')
            self.assertEqual(x['env'], [])
            self.assertEqual(x['command'][:2], ['/bin/bash', '-c'])
            self.assertIn('--harness '+provision.HARNESSES[i], x['command'][2])
            self.assertIn('--concurrency 16', x['command'][2])
            self.assertIn(provision.HARNESSES[i]+'.json', x['command'][2])
            self.assertIn('bootstrap_bc_bounded_retry_v1.py', x['command'][2])
            self.assertNotIn('bootstrap_mmbc100_cci.py', x['command'][2])

    def test_changed_resource_and_old_root_rejected(self):
        c=self.template(); c['template']['containers'][0]['resource_request']['cpu']='16'
        with self.assertRaises(ValueError): provision.build_config(c,'hermes')
        with self.assertRaises(ValueError): provision.build_config(self.template(),'hermes',ROOT/'outputs/campaigns/mmbc100-hermes-deepseek-v1')
        for bad in (True,-1,3,'1','scale_0125'):
            with self.assertRaises(ValueError): provision.app_name(bad)

    def test_bootstrap_commands_bind_scope(self):
        args=SimpleNamespace(root=provision.DEFAULT_ROOT,harness='dsh',reader_python='/opt/conda/bin/python')
        commands=boot.commands(args)
        self.assertIn('dsh',commands['controller'])
        self.assertIn('--resume',commands['controller'])
        self.assertIn(str(ROOT/'scripts/run_bc_bounded_retry_v1.py'),commands['controller'])
        self.assertIn(str(provision.DEFAULT_ROOT/'experiment.json'),commands['web_preflight'])
        self.assertIn('--harness',commands['telemetry'])
        self.assertEqual(commands['reader'][-1],str(boot.base.READER_CONFIG))

    def test_existing_submission_never_repeated(self):
        with tempfile.TemporaryDirectory() as td:
            d=Path(td); (d/'request.json').write_text('{}')
            def forbidden(argv): raise AssertionError('No network on existing request')
            result=provision.submit({'name':provision.app_name('hermes'),'config_path':str(d/'config.yaml')},forbidden)
            self.assertEqual(result['state'],'existing_request_never_repeated')

    def test_ambiguous_absence_prevents_creation(self):
        with tempfile.TemporaryDirectory() as td:
            calls=[]
            def unavailable(argv): calls.append(argv); return {'returncode':1,'stdout':'','stderr':'Unavailable'}
            with self.assertRaises(ValueError):
                provision.submit({'name':provision.app_name('dsh'),'config_path':str(Path(td)/'config.yaml')},unavailable)
            self.assertEqual(len(calls),1)
            self.assertIn('describe',calls[0])
            self.assertFalse((Path(td)/'request.json').exists())


if __name__ == '__main__': unittest.main()
