import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_bc_trial_v3_io as maintenance
import run_bc_campaign_v3 as original_controller
import run_bc_campaign_v3_io as controller


class HeartbeatMaintenanceTests(unittest.TestCase):
    def writer(self):
        strict = Mock()
        writer = maintenance.HeartbeatAtomic(strict, sleep=Mock())
        writer.diagnostic = Mock()
        return writer, strict

    def test_transient_fsync_keeps_failed_temp_and_recovers(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'heartbeat.json'
            writer, strict = self.writer()
            with patch.object(maintenance.os, 'fsync', side_effect=[OSError(errno.EIO, 'injected'), None]):
                writer(path, {'alive': True})
            self.assertEqual(json.loads(path.read_text()), {'alive': True})
            self.assertEqual(len(list(Path(td).glob('*.tmp'))), 1)
            records = [call.args[1] for call in writer.diagnostic.call_args_list]
            self.assertEqual(records[0]['stage'], 'fsync')
            self.assertEqual(records[0]['errno'], errno.EIO)
            self.assertTrue(records[0]['will_retry'])
            self.assertEqual(records[1]['event'], 'heartbeat_write_recovered')
            self.assertEqual(records[1]['attempt_number'], 2)
            strict.assert_not_called()

    def test_rename_estale_recovers_and_does_not_delete_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            writer, _ = self.writer(); path = Path(td) / 'heartbeat.json'
            original = Path.replace; attempts = []
            def replace(source, target):
                attempts.append(source)
                if len(attempts) == 1: raise OSError(errno.ESTALE, 'injected')
                return original(source, target)
            with patch.object(Path, 'replace', replace): writer(path, {'x': 1})
            self.assertEqual(writer.diagnostic.call_args_list[0].args[1]['stage'], 'replace')
            self.assertTrue(attempts[0].exists())
            self.assertTrue(path.exists())

    def test_permanent_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as td:
            writer, _ = self.writer()
            with patch.object(maintenance.os, 'fsync', side_effect=OSError(errno.EACCES, 'injected')):
                with self.assertRaises(OSError) as raised: writer(Path(td) / 'heartbeat.json', {})
            self.assertEqual(raised.exception.errno, errno.EACCES)
            writer.sleep.assert_not_called()
            self.assertFalse(writer.diagnostic.call_args.args[1]['will_retry'])

    def test_retry_exhaustion_still_raises_and_preserves_all_temps(self):
        with tempfile.TemporaryDirectory() as td:
            writer, _ = self.writer()
            with patch.object(maintenance.os, 'fsync', side_effect=OSError(errno.EIO, 'injected')):
                with self.assertRaises(OSError): writer(Path(td) / 'heartbeat.json', {})
            self.assertEqual(writer.sleep.call_count, 3)
            self.assertEqual(writer.diagnostic.call_count, 4)
            self.assertEqual(len(list(Path(td).glob('*.tmp'))), 4)
            self.assertFalse(writer.diagnostic.call_args.args[1]['will_retry'])

    def test_claim_result_writes_remain_strict(self):
        writer, strict = self.writer()
        for name in ['result.json', 'owner.json', 'spec.json']:
            writer(Path('/fixture') / name, {'value': 1})
        self.assertEqual(strict.call_count, 3)
        writer.diagnostic.assert_not_called()
        writer.sleep.assert_not_called()

    def test_local_diagnostic_and_shared_sidecar(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); attempt = root / 'attempt'; attempt.mkdir()
            writer = maintenance.HeartbeatAtomic(Mock(), local_dir=root / 'local')
            writer.diagnostic(attempt / 'heartbeat.json', {'event': 'injected', 'stage': 'fsync', 'errno': errno.EIO})
            local = next((root / 'local').glob('*.jsonl'))
            self.assertEqual(local.read_text(), (attempt / 'heartbeat-io.jsonl').read_text())
            self.assertEqual(local.stat().st_mode & 0o777, 0o600)

    def test_controller_only_dispatch_and_sidecar_change(self):
        self.assertIs(controller.validate_sources, original_controller.validate_sources)
        self.assertIs(controller.acquire_claim, original_controller.acquire_claim)
        self.assertIs(controller.prepare, original_controller.prepare)
        old = (ROOT / 'scripts/run_bc_campaign_v3.py').read_text().split('def main():', 1)[1]
        new = (ROOT / 'scripts/run_bc_campaign_v3_io.py').read_text().split('def main():', 1)[1]
        new = new.replace("'scripts/run_bc_trial_v3_io.py'", "'scripts/run_bc_trial_v3.py'")
        new = new.replace("    atomic(control/'maintenance.json', maintenance_record())\n", '')
        self.assertEqual(new, old)


if __name__ == '__main__': unittest.main()
