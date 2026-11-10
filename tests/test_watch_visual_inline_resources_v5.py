import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from watch_visual_inline_resources_v5 import refresh_once,load_cells

class ObserverTests(unittest.TestCase):
    def sample(self):
        return {'scan_finished_at':'fixture','client_scan_seconds':1,'observed_http_attempts':3,
                'unknown_usage_attempts':1,'accounting_issues':{},
                'alias_and_conservation_issues':{'prompt_invalid_or_conflicting':1}}
    def test_failed_collection_keeps_previous_success_exactly(self):
        with tempfile.TemporaryDirectory()as directory:
            out=Path(directory);current=out/'resources-current.json';current.write_bytes(b'{"prior":"unchanged"}\n')
            def failure(root,output):raise OSError('Do not log potentially sensitive exception text')
            ok,status=refresh_once('/source',out,builder=failure)
            self.assertFalse(ok);self.assertEqual(current.read_bytes(),b'{"prior":"unchanged"}\n')
            self.assertEqual(status['error_type'],'OSError');self.assertNotIn('sensitive',(out/'resources-observer-status.json').read_text())
    def test_failed_serialization_keeps_previous_success_exactly(self):
        with tempfile.TemporaryDirectory()as directory:
            out=Path(directory);current=out/'resources-current.json';current.write_bytes(b'previous')
            ok,_=refresh_once('/source',out,builder=lambda *_:{'invalid':object()})
            self.assertFalse(ok);self.assertEqual(current.read_bytes(),b'previous');self.assertEqual(list(out.glob('*.tmp')),[])
    def test_success_publishes_unknown_and_alias_counts(self):
        with tempfile.TemporaryDirectory()as directory:
            out=Path(directory);value=self.sample();ok,status=refresh_once('/source',out,builder=lambda *_:value)
            self.assertTrue(ok);self.assertEqual(json.loads((out/'resources-current.json').read_text()),value)
            self.assertEqual(status['unknown_usage_attempts'],1);self.assertEqual(status['alias_and_conservation_issues'],{'prompt_invalid_or_conflicting':1})
            self.assertEqual((out/'resources-current.json').stat().st_mode&0o777,0o600)
    def test_changed_plan_binding_is_rejected_before_accounting(self):
        with tempfile.TemporaryDirectory()as directory:
            root=Path(directory);cell=root/'cells/c';cell.mkdir(parents=True);(cell/'plan.json').write_text('{"jobs":[]}')
            (root/'inventory.json').write_text(json.dumps({'cells':[{'cell':'c','plan_sha256':'wrong'}]}))
            with self.assertRaisesRegex(ValueError,'binding'):load_cells(root)
if __name__=='__main__':unittest.main()
