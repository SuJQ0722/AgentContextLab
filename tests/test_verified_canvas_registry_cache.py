import hashlib
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verified_canvas_registry_cache import VerifiedCanvasRegistryCache


class VerifiedRegistryTests(unittest.TestCase):
    def test_reuses_validation_but_not_returned_mutable_set(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'page'; p.write_bytes(b'original')
            calls, rows = [], []
            def validate(root):
                calls.append(root)
                return {hashlib.sha256(p.read_bytes()).hexdigest()}
            cache = VerifiedCanvasRegistryCache(d, validate, rows.append)
            expected = cache()
            time.sleep(2.1)  # Leave coarse filesystem timestamp update window.
            cache().clear()
            self.assertEqual(cache(), expected)
            self.assertEqual(len(calls), 1)
            self.assertEqual([r['cache_hit'] for r in rows], [False, True, True])

    def test_rechecks_same_size_change_even_with_restored_mtime(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'page'; p.write_bytes(b'old')
            calls = []
            def validate(root):
                calls.append(1)
                return {p.read_bytes()}
            cache = VerifiedCanvasRegistryCache(d, validate)
            self.assertEqual(cache(), {b'old'})
            s = p.stat(); p.write_bytes(b'new')
            os.utime(p, ns=(s.st_atime_ns, s.st_mtime_ns))
            self.assertEqual(cache(), {b'new'})
            self.assertEqual(len(calls), 2)

    def test_new_removed_nested_artifacts_and_failed_validation(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'sub').mkdir(); p = root / 'sub/page'
            calls = []
            def validate(directory):
                calls.append(1)
                if p.exists() and p.read_text() == 'invalid':
                    raise ValueError('digest mismatch')
                return {p.read_text()} if p.exists() else set()
            cache = VerifiedCanvasRegistryCache(root, validate)
            self.assertEqual(cache(), set())
            p.write_text('valid'); self.assertEqual(cache(), {'valid'})
            p.write_text('invalid')
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, 'digest mismatch'): cache()
            p.unlink(); self.assertEqual(cache(), set())
            self.assertEqual(len(calls), 5)

    def test_mutation_during_validation_and_symlink_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'page'; p.write_text('before')
            def changing(root):
                p.write_text('after')
                return {'untrusted'}
            with self.assertRaisesRegex(ValueError, 'changed during'):
                VerifiedCanvasRegistryCache(d, changing)()
            q = Path(d) / 'link'; q.symlink_to(p)
            with self.assertRaisesRegex(ValueError, 'symlinks'):
                VerifiedCanvasRegistryCache(d, lambda root: {'untrusted'})()


if __name__ == '__main__':
    unittest.main()
