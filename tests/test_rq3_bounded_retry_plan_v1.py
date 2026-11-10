import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import prepare_rq3_bounded_retry_v1 as plan
import run_rq3_bounded_retry_v1 as controller


class FailureOnlyTests(unittest.TestCase):
    def row(self, directory, status, score=None):
        attempt=Path(directory)/status;attempt.mkdir(exist_ok=True)
        result={'job_id':'hermes/scale_0750/q_001_r01','question_id':'q_001','repeat':1,
                'status':status,'slot_released':True,'unconfirmed_child_termination':[]}
        (attempt/'result.json').write_text(json.dumps(result))
        return {**result,'attempt':str(attempt),'prediction_status':status,'scale':.75,'score':score}

    def test_completed_wrong_and_ungraded_are_not_selected(self):
        with tempfile.TemporaryDirectory() as d:
            for score in (0,1,None):
                r=self.row(d,'completed',score)
                self.assertFalse(plan.classify(r)['selected_for_retry'])

    def test_only_clean_timeout_and_failed_are_selected(self):
        with tempfile.TemporaryDirectory() as d:
            for status in ('timeout','failed'):
                row=self.row(d,status)
                self.assertTrue(plan.classify(row)['selected_for_retry'])
            row=self.row(d,'interrupted')
            with self.assertRaises(ValueError):plan.classify(row)
            row=self.row(d,'timeout');p=Path(row['attempt'])/'result.json';r=json.loads(p.read_text());r['slot_released']=False;p.write_text(json.dumps(r))
            with self.assertRaises(ValueError):plan.classify(row)

    def test_changed_source_identity_or_stale_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            row=self.row(d,'failed');row['question_id']='wrong'
            with self.assertRaises(ValueError):plan.classify(row)
            row=self.row(d,'failed');row['prediction_status']='timeout'
            with self.assertRaises(ValueError):plan.classify(row)

    def test_all_seven_scales_keep_individual_values_and_zero_semantics(self):
        base={'visual_renderer':{},'shared_policy':{'strategy_configs':{'visual':{}}}}
        for scale in plan.SCALES:
            c=plan.scale_config(base,scale,'approved')
            self.assertEqual(c['visual_renderer']['history_scale'],scale)
            self.assertEqual(c['shared_policy']['strategy_configs']['visual']['history_scale'],scale)
            self.assertIn('far history only',c['rq3']['zero_semantics'])
            self.assertFalse(c['rq3']['mixed_protocol_overlay_is_clean_resolution_ablation'])
        self.assertNotIn('model',base)

    def test_scale_selection_is_disjoint(self):
        jobs=[{'job_id':'hermes/'+k+'/q_001_r01','harness':'hermes','strategy':'visual',
               'scale_key':k,'bounded_rq3_protocol':plan.PROTOCOL} for k in plan.SCALE_KEYS]
        p={'definition':{'scale_keys':list(plan.SCALE_KEYS),'per_cell_concurrency_cap':112},'jobs':jobs}
        self.assertEqual([len(controller.selected_jobs(p,k)) for k in plan.SCALE_KEYS],[1]*7)
        with self.assertRaises(ValueError):controller.selected_jobs(p,'scale_0125')

    def test_each_scale_has_16_slots_without_changing_native_strategy(self):
        job={'job_id':'hermes/scale_0250/q_001_r01','strategy':'visual','scale_key':'scale_0250'}
        with patch.object(controller,'original_acquire_claim',return_value='ok') as acquire:
            self.assertEqual(controller.acquire_claim(Path('/new'),job,{'id':'owner'}),'ok')
            args,kwargs=acquire.call_args
            self.assertEqual(args[1]['strategy'],'scale_0250');self.assertEqual(kwargs['cap'],16)
            self.assertEqual(job['strategy'],'visual')


if __name__=='__main__':unittest.main()
