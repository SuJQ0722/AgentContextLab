import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_bc_trial_v3_io2 as maintenance
import run_bc_trial_v3 as frozen
import run_bc_campaign_v3_io2 as controller
import run_bc_campaign_v3 as original_controller


class SingleValidationTests(unittest.TestCase):
    def test_original_trial_validates_once_marker_after_validation_before_launch(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td); calls = []
            def validate(spec, path):
                calls.append('validate')
                self.assertFalse((path / 'maintenance.json').exists())
                return 'validated-root'
            validate_spy = Mock(side_effect=validate)
            def atomic(path, record):
                calls.append('marker')
                path.write_text(json.dumps(record))
            def original_main():
                self.assertEqual(frozen.validate_spec({}, out), 'validated-root')
                self.assertTrue((out / 'maintenance.json').exists())
                calls.append('native_launch')
            with patch.object(frozen, 'validate_spec', validate_spy), patch.object(frozen, 'atomic', atomic), patch.object(frozen, 'main', original_main):
                maintenance.main()
                self.assertIs(frozen.validate_spec, validate_spy)
            self.assertEqual(calls, ['validate', 'marker', 'native_launch'])
            validate_spy.assert_called_once()

    def test_validation_failure_neither_marks_nor_launches(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td); launched = Mock(); atomic = Mock()
            validate = Mock(side_effect=ValueError('frozen-source-changed'))
            def original_main():
                frozen.validate_spec({}, out)
                launched()
            with patch.object(frozen, 'validate_spec', validate), patch.object(frozen, 'atomic', atomic), patch.object(frozen, 'main', original_main):
                with self.assertRaises(ValueError): maintenance.main()
            validate.assert_called_once(); atomic.assert_not_called(); launched.assert_not_called()

    def test_hashes_include_v1_dependency_and_both_v2_entries(self):
        record = maintenance.maintenance_record()
        self.assertEqual(record['maintenance_version'], 'bc-v3-heartbeat-io-v2')
        self.assertEqual(set(record['implementation_sha256']), {
            'scripts/run_bc_trial_v3_io.py', 'scripts/run_bc_trial_v3_io2.py', 'scripts/run_bc_campaign_v3_io2.py'})

    def test_controller_still_shares_frozen_validation_claims_and_slots(self):
        self.assertIs(controller.validate_sources, original_controller.validate_sources)
        self.assertIs(controller.acquire_claim, original_controller.acquire_claim)
        before = (ROOT / 'scripts/run_bc_campaign_v3_io.py').read_text().split('def main():', 1)[1]
        after = (ROOT / 'scripts/run_bc_campaign_v3_io2.py').read_text().split('def main():', 1)[1]
        self.assertEqual(after.replace('run_bc_trial_v3_io2.py', 'run_bc_trial_v3_io.py'), before)


if __name__ == '__main__': unittest.main()
