import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from route_attribution_routes1 import RouteAttributionMixin,load_route_lineage
from hermes_bc_worker import Recorder
import monitor_bc_campaign_v3 as monitor

class RoutedRecorder(RouteAttributionMixin,Recorder):pass

class RouteAttributionTests(unittest.TestCase):
    def test_hermes_archive_preserved_sidecar_revisions_do_not_duplicate_usage(self):
        with tempfile.TemporaryDirectory() as temporary:
            attempt=Path(temporary);metrics=attempt/'native/metrics';lineage=attempt/'route-lineage.json'
            lineage.write_text(json.dumps({'logical_model':'deepseek-v4.1-flash-1017/huoshan/huoshan',
              'actual_route':'deepseek-v4.1-flash-1017/zijian/sfb','runtime_route_version':'routes1'}))
            with patch.dict(os.environ,{'ACL_ROUTE_LINEAGE_FILE':str(lineage)}):recorder=RoutedRecorder(metrics)
            request={'type':'request','call_id':'one','model':'deepseek-v4.1-flash-1017/zijian/sfb','messages':[{'content':'PRIVATE'}]}
            recorder.archive(request)
            recorder.write('calls.jsonl',{'call_id':'one','model':request['model'],'purpose':'compaction',
              'raw_provider_usage':{'prompt_tokens':10,'completion_tokens':2,'total_tokens':12},'client_stream_seconds':1})
            recorder.archive({'type':'response','call_id':'one','response':{'model':'deepseek-v4-1-flash-261017','choices':[{'message':{'content':'SECRET'}}]}})
            sidecars=[json.loads(line) for line in (metrics/'route-attribution.jsonl').read_text().splitlines()]
            self.assertEqual(len(sidecars),2);self.assertEqual(sidecars[-1]['returned_model'],'deepseek-v4-1-flash-261017')
            self.assertTrue(sidecars[-1]['returned_model_matches_preflight_observation']);self.assertFalse(sidecars[-1]['returned_model_exactly_matches_request_alias']);self.assertIsNone(sidecars[-1]['backend_weights_equivalence_verified'])
            self.assertFalse(sidecars[-1]['cached_input_presence']);self.assertFalse(sidecars[-1]['usage_authority'])
            self.assertNotIn('SECRET',json.dumps(sidecars));self.assertNotIn('PRIVATE',json.dumps(sidecars))
            with gzip.open(metrics/'requests-responses.jsonl.gz','rt') as stream:self.assertEqual(json.loads(next(stream)),request)
            row,raw=monitor.inspect_attempt(attempt,'hermes')
            self.assertEqual(len(raw),1);self.assertEqual(row['usage']['fields']['total']['complete_total'],12)
            self.assertIsNone(row['usage']['fields']['cached_input']['complete_total'])
            group=row['route_accounting']['route_generation_groups'][0]
            self.assertEqual(group['actual_route'],request['model']);self.assertEqual(group['runtime_generation'],'routes1')
            self.assertEqual(group['usage']['observations'],1)

    def test_unknown_request_route_is_not_filled_from_assignment(self):
        with tempfile.TemporaryDirectory() as temporary:
            attempt=Path(temporary);metrics=attempt/'metrics';metrics.mkdir()
            (attempt/'route-lineage.json').write_text(json.dumps({'actual_route':'assigned-only','runtime_route_version':'routes1'}))
            rows=monitor.attribute_usage_rows([{'call_id':'missing','raw_provider_usage':None}],metrics,'hermes',attempt,[])
            self.assertIsNone(rows[0]['_actual_route'])
            result=monitor.route_accounting(rows)
            self.assertEqual(result['route_unknown_observations'],1)
            self.assertIsNone(result['usage_by_route']['unknown']['fields']['prompt']['complete_total'])

    def test_runtime_lineage_rejects_model_or_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);config=root/'runtime-config.json';spec=root/'runtime-spec.json';lineage=root/'route-lineage.json'
            config.write_text('{}');spec.write_text('{}')
            data={'actual_route':'route','runtime_config_path':str(config),'runtime_spec_path':str(spec),
              'runtime_config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),'runtime_spec_sha256':hashlib.sha256(spec.read_bytes()).hexdigest()}
            lineage.write_text(json.dumps(data))
            with patch.dict(os.environ,{'ACL_ROUTE_LINEAGE_FILE':str(lineage)}):
                self.assertEqual(load_route_lineage('route',config,spec)['actual_route'],'route')
                with self.assertRaises(ValueError):load_route_lineage('other',config,spec)
                config.write_text('{"changed":true}')
                with self.assertRaises(ValueError):load_route_lineage('route',config,spec)

    def test_hermes_native_install_guards_are_inherited_unchanged(self):
        import hermes_bc_worker_routes1 as routes
        import hermes_bc_worker_v3 as parent
        self.assertIs(routes.RoutedTextRecorder.install,parent.ReviewedTextRecorder.install)
        self.assertIs(routes.RoutedVisionRecorder.install,parent.VisionRecorder.install)

if __name__=='__main__':unittest.main()
