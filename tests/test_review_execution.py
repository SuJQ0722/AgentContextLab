import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from review_execution import ROOT, VERSION, enforce
from prepare_sco_review import expand


class ReviewExecutionTests(unittest.TestCase):
    def test_fixture_cannot_target_paid_gateway(self):
        cfg = {'execution_version': VERSION, 'web': {'fetch_base_url': 'http://127.0.0.1:1', 'search_host': '127.0.0.1'}}
        with self.assertRaisesRegex(ValueError, 'loopback'):
            enforce(cfg, {'TOKENHUB_BASE_URL': 'https://gateway.example/v1'}, ROOT/'outputs/preflight/test', offline_fixture=True)
        enforce(cfg, {'TOKENHUB_BASE_URL': 'http://127.0.0.1:1/v1'}, ROOT/'outputs/preflight/test', offline_fixture=True)

    def test_repaired_workers_cannot_mutate_old_campaign(self):
        with self.assertRaisesRegex(ValueError, 'historical'):
            enforce({'execution_version': VERSION, 'review_approved': True}, {}, ROOT/'outputs/campaigns/bc100-r3-all-strategies/new')

    def test_review_plan_is_only_a_matrix(self):
        plan = json.loads((ROOT/'configs/sco-review-plan.json').read_text())
        plan['launch_authorized'] = False
        result = expand(plan)
        self.assertEqual(result['totals'], dict(instances=22, vcpus=176, memory_gib=704, worker_slots=704))
        self.assertEqual(result['state'], 'review_only_not_submittable')
        plan['launch_authorized'] = True
        authorized = expand(plan)
        self.assertEqual(authorized['state'], 'authorized_not_submittable')
        self.assertTrue(authorized['launch_authorized'])
        self.assertEqual(authorized['cells'], result['cells'])
        plan['launch_authorized'] = 'yes'
        with self.assertRaises(ValueError):
            expand(plan)
