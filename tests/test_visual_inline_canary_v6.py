import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_visual_inline_canary_v6 as prepare
from inline_route_contract_v2 import validate_routes
from inline_route_contract_v1 import ROUTES


class CanaryTests(unittest.TestCase):
    def test_completed_is_retained_and_only_clean_timeout_selected(self):
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)
            jobs = [{'job_id': 'h/visual/a'}, {'job_id': 'h/visual/b'}]
            for job, status in zip(jobs, ['completed', 'timeout']):
                p = source / 'jobs' / job['job_id'] / 'attempts/attempt_001/result.json'
                p.parent.mkdir(parents=True)
                p.write_text(json.dumps({'status': status, 'slot_released': True, 'unconfirmed_child_termination': []}))
            plan = {'jobs': jobs, 'definition': {'source_results_sha256': {}}}
            self.assertEqual(prepare.select_failed(source, plan)[0]['job_id'], 'h/visual/b')
            ancestor = source / 'prior/jobs/h/visual/b/attempts/attempt_001/result.json'
            ancestor.parent.mkdir(parents=True); ancestor.write_text('{"status":"completed"}')
            plan['definition']['source_results_sha256'][str(ancestor)] = 'bound-by-source-validator'
            with self.assertRaises(ValueError): prepare.select_failed(source, plan)

    def test_transport_freeze_cannot_change_deadline_or_tokens(self):
        with self.assertRaisesRegex(ValueError, 'scientific budgets'):
            prepare.freeze({'timeout_seconds': 7200}, [])

    def test_real_v4_contract_requires_explicit_proxy(self):
        cfg = {'model_route_policy': 'four-route-rotation-v1', 'approved_model_routes': ROUTES,
               'image_transport': 'inline-recent-ten-chunked-v1', 'transport_delivery_version': 'inline-direct-v1',
               'transport_runtime_version': 'visual-transport-runtime-v4', 'model': ROUTES[0],
               'gateway_proxy': 'http://10.120.0.246:7890'}
        validate_routes(cfg, cfg)
        with self.assertRaises(ValueError): validate_routes({**cfg, 'transport_runtime_version': 'visual-transport-runtime-v3'}, cfg)
        with self.assertRaises(ValueError): validate_routes({**cfg, 'gateway_proxy': None}, cfg)


if __name__ == '__main__': unittest.main()
