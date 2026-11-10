import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import report_visual_transport_latency_v5 as report

def save(path,value):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
def lines(path,values):path.parent.mkdir(parents=True,exist_ok=True);path.write_text(''.join(json.dumps(v)+'\n'for v in values))
class LatencyTests(unittest.TestCase):
 def test_routes_real_phases_wait_and_missing_are_separate(self):
  with tempfile.TemporaryDirectory()as d:
   cell=Path(d)/'cells/bc_hermes';save(cell/'plan.json',{})
   a=cell/'jobs/hermes/visual/q1/attempts/attempt_001';save(a/'result.json',{'status':'completed','end_to_end_seconds':110,'native_end_to_end_seconds':105})
   ledger=a/'native/metrics/transport-phases-v3.jsonl'
   lines(ledger,[{'event':'request_started','request_id':'r1','route':'first'}, {'event':'response_headers','request_id':'r1','route':'first','status_code':429,'elapsed_seconds':2}, {'event':'route_backoff','request_id':'r1','route':'first','client_wait_seconds':60}, {'event':'request_started','request_id':'r2','route':'second'}, {'event':'transport_phase','request_id':'r2','route':'second','phase':'http11.send_request_body.complete','phase_seconds':4}, {'event':'response_headers','request_id':'r2','route':'second','elapsed_seconds':7}, {'event':'stream_complete','request_id':'r2','route':'second','elapsed_seconds':10,'client_stream_seconds':3}])
   (cell/'jobs/hermes/visual/q2/attempts/attempt_001').mkdir(parents=True)
   out=report.report(Path(d))['cells'][0]
   self.assertEqual(out['trial_end_to_end']['observed_count'],1);self.assertEqual(out['trial_end_to_end']['missing_count'],1)
   self.assertIsNone(out['native_render']['known_subtotal_seconds']);self.assertEqual(out['native_render']['attempts_without_render_records'],2)
   self.assertIsNone(out['provider_internal_latency_seconds'])
   first=out['per_actual_route']['first']['client_metrics'];second=out['per_actual_route']['second']['client_metrics']
   self.assertEqual(first['quota_backoff_wait']['known_subtotal_seconds'],60);self.assertIsNone(first['request_upload']['mean_seconds'])
   self.assertEqual(second['request_upload']['mean_seconds'],4);self.assertEqual(second['response_stream']['mean_seconds'],3)
 def test_partial_live_jsonl_keeps_valid_events_and_missing_route(self):
  with tempfile.TemporaryDirectory()as d:
   cell=Path(d);a=cell/'jobs/h/visual/q/attempts/attempt_001';f=a/'native/metrics/transport-phases-v3.jsonl';lines(f,[{'event':'response_headers','elapsed_seconds':1}]);f.write_text(f.read_text()+'{"event":')
   out=report.cell_report(cell);self.assertIn('missing_actual_route',out['per_actual_route']);self.assertEqual(len(out['issues']),1)
 def test_dsh_routes_share_sdk_but_keep_http_attempts_and_actual_wait(self):
  with tempfile.TemporaryDirectory()as d:
   cell=Path(d);a=cell/'jobs/dsh/visual/q/attempts/attempt_001';f=a/'native/workspace/metrics/inline-images-wire-dsh-v1.jsonl'
   lines(f,[{'event':'final_inline_request','sdk_request_id':'sdk','attempt_id':'a','actual_model':'routeA'}, {'event':'request_body_sent','sdk_request_id':'sdk','attempt_id':'a','actual_model':'routeA','client_seconds':4}, {'event':'response_headers','attempt_id':'a','actual_model':'routeA','http_status':429,'client_seconds':5}, {'event':'final_inline_request','sdk_request_id':'sdk','attempt_id':'b','actual_model':'routeB'}, {'event':'response_headers','attempt_id':'b','actual_model':'routeB','client_seconds':7}, {'event':'stream_complete','attempt_id':'b','actual_model':'routeB','client_seconds':10}, {'event':'route_backoff_complete','sdk_request_id':'sdk','client_wait_seconds':60.5}])
   out=report.cell_report(cell);routes=out['per_actual_route']
   self.assertEqual(routes['routeA']['http_request_ids'],1);self.assertEqual(routes['routeB']['http_request_ids'],1)
   self.assertEqual(routes['routeA']['client_metrics']['time_to_request_body_sent']['mean_seconds'],4)
   self.assertIsNone(routes['routeA']['client_metrics']['request_upload']['mean_seconds'])
   self.assertEqual(routes['routeB']['client_metrics']['response_stream']['mean_seconds'],3)
   self.assertEqual(routes['shared_route_cycle_wait']['client_metrics']['quota_backoff_wait']['mean_seconds'],60.5)
 def test_negative_or_unmeasured_is_not_zero(self):
  out=report.summary([None,-1,float('nan')]);self.assertEqual(out['missing_count'],3);self.assertIsNone(out['mean_seconds']);self.assertIsNone(out['known_subtotal_seconds'])
if __name__=='__main__':unittest.main()
