import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_controlled_bounded_v1 as queue
import prepare_controlled_bounded_v1 as prep
from controlled_native_report_v4 import aggregate


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name)
        self.prefix='mmbrowsecomp/q_001_r01'

    def job(self,method='summary'):
        out=self.root/'jobs'/self.prefix/method; out.mkdir(parents=True,exist_ok=True)
        spec=out/'spec.json'; spec.write_text(json.dumps({'bounded_transport_encoding':prep.ENCODING}))
        return {'job_id':self.prefix+'/'+method,'prefix_key':self.prefix,'out':str(out),'eligible':True,'method':method,'spec_path':str(spec)}

    def control(self,n=10000):
        return {'passed':True,'method':'visual','first_actual_prompt_tokens':n,'native_identity_verified':True,
            'native_hashes':['native-one'],'prefix_sha256':'prefix','actual_route':prep.MODEL,
            'bounded_native_protocol':queue.PROTOCOL,'bounded_transport_encoding':prep.ENCODING}

    def test_text_waits_for_final_new_visual_not_old_success(self):
        job=self.job(); visual=self.job('visual'); out=Path(visual['out'])
        (out/'compression-control.json').write_text(json.dumps(self.control()))
        self.assertEqual(queue.disposition(job,self.root),'waiting_visual')
        (out/'trial-status.json').write_text(json.dumps({'status':'failed'}))
        self.assertEqual(queue.disposition(job,self.root),'ready') # Valid first intervention even if continuation fails.
        c=self.control();c['bounded_native_protocol']={'old':True}
        (out/'compression-control.json').write_text(json.dumps(c))
        self.assertEqual(queue.disposition(job,self.root),'not_run_visual_gate_unavailable')

    def test_result_or_dispatch_never_automatically_replayed(self):
        for marker in ('dispatch.json','worker-started.json','result.json','supervisor.json'):
            with self.subTest(marker=marker):
                job=self.job('visual'); p=Path(job['out'])/marker; p.write_text('{}')
                self.assertEqual(queue.disposition(job,self.root),'interrupted_unknown_no_replay');p.unlink()

    def test_unavailable_not_replaced_and_no_paid_ready(self):
        job=self.job('visual');job['eligible']=False
        self.assertEqual(queue.disposition(job,self.root),'not_run_original_prefix_unavailable')
        p=self.root/'absent.json'; e={'key':'same-original-key','pilot':False,'spec':{'dataset':'mmbrowsecomp','prefix_path':str(p)}}
        result=prep.audit_prefix(e)
        self.assertFalse(result['eligible']);self.assertEqual(result['key'],e['key'])

    def test_running_visual_blocks_text_even_valid_control(self):
        job=self.job(); visual=self.job('visual');out=Path(visual['out'])
        (out/'trial-status.json').write_text('{}');(out/'compression-control.json').write_text(json.dumps(self.control()))
        with patch.object(queue,'alive',side_effect=lambda p:p==out):
            self.assertEqual(queue.disposition(job,self.root),'waiting_visual')

    def test_actual_two_percent_and_native_and_spread_gate(self):
        rows={k:self.control(n) for k,n in [('visual',10000),('summary',10200),('window',9800)]}
        self.assertTrue(queue.group_gate(rows)['passed'])
        rows['summary']['first_actual_prompt_tokens']=10201
        self.assertFalse(queue.group_gate(rows)['passed'])
        rows['summary']['first_actual_prompt_tokens']=10000;rows['window']['native_hashes']=['changed']
        self.assertFalse(queue.group_gate(rows)['passed'])

    def test_unknown_usage_not_filled_zero(self):
        r=aggregate([{'raw_provider_usage':{'prompt_tokens':100,'completion_tokens':2,'total_tokens':102}}, {'raw_provider_usage':None}])
        self.assertIsNone(r['complete_totals']['cached']);self.assertIsNone(r['complete_totals']['total'])
        self.assertEqual(r['known_subtotals']['total'],102);self.assertEqual(r['missing_by_field']['total'],1)

    def test_provider_route_mismatch_fails(self):
        c=self.control();c['actual_route']='old-route'
        self.assertFalse(queue.reference_valid(c,{'bounded_transport_encoding':prep.ENCODING}))

if __name__=='__main__':unittest.main()
