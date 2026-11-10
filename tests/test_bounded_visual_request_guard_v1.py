import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import bounded_visual_request_guard_v1 as guard


def fixture(width=12, height=8):
    buffer = io.BytesIO()
    Image.new('RGB', (width, height), 'white').save(buffer, format='PNG')
    data = buffer.getvalue()
    return {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' +
            base64.b64encode(data).decode(), 'detail': 'high'}}, hashlib.sha256(data).hexdigest()


def body(parts):
    return json.dumps({'model': 'fixture', 'messages': [{'role': 'user', 'content': parts}]}).encode()


class BoundedImageGuardTests(unittest.TestCase):
    def test_exact_serialized_body_boundary(self):
        raw = body([])
        at_limit = raw + b' ' * (guard.MAX_BODY_BYTES - len(raw))
        self.assertEqual(guard.inspect_payload(at_limit)['body_bytes'], guard.MAX_BODY_BYTES)
        with self.assertRaises(guard.BoundedVisualRequestError) as caught:
            guard.inspect_payload(at_limit + b' ')
        self.assertIn('body_exceeds_8_mib', caught.exception.ledger['violations'])
        with self.assertRaises(TypeError): guard.inspect_payload({'messages': []})

    def test_count_includes_duplicate_native_images(self):
        part, sha = fixture()
        self.assertEqual(guard.inspect_payload(body([part] * 32))['image_count'], 32)
        with self.assertRaises(guard.BoundedVisualRequestError) as caught:
            guard.inspect_payload(body([part] * 33), rendered_registry=set(), strict_all_images=False)
        self.assertIn('image_count_exceeds_32', caught.exception.ledger['violations'])

    def test_canvas_side_and_area_independent_and_exact_boundary(self):
        part, sha = fixture(1024, 2048)
        self.assertTrue(guard.inspect_payload(body([part]), rendered_registry={sha})['images'][0]['rendered_canvas'])
        for size, violation in [((20, 2049), 'canvas_side_exceeds_2048'),
                                ((1025, 2048), 'canvas_area_exceeds_2097152')]:
            part, sha = fixture(*size)
            with self.assertRaises(guard.BoundedVisualRequestError) as caught:
                guard.inspect_payload(body([part]), rendered_registry={sha}, strict_all_images=False)
            self.assertIn(violation, caught.exception.ledger['violations'])

    def test_native_bytes_and_large_dimensions_are_preserved(self):
        part, sha = fixture(3000, 1200)
        raw = body([part])
        row = guard.inspect_payload(raw, rendered_registry=set(), strict_all_images=False)
        self.assertFalse(row['images'][0]['rendered_canvas'])
        self.assertEqual(row['images'][0]['sha256'], sha)
        self.assertEqual(row['images'][0]['width'], 3000)
        with self.assertRaises(guard.BoundedVisualRequestError): guard.inspect_payload(raw)
        with self.assertRaises(guard.BoundedVisualRequestError):
            guard.inspect_payload(raw, strict_all_images=False)

    def test_url_and_bad_inline_fail_closed_without_leaking(self):
        for value in ['https://example.test/private-image?credential=do-not-log',
                      'data:image/png;base64,%%%bad', 'data:image/png,not-base64']:
            with self.assertRaises(guard.BoundedVisualRequestError) as caught:
                guard.inspect_payload(body([{'type': 'image_url', 'image_url': {'url': value}}]))
            self.assertNotIn(value, json.dumps(caught.exception.ledger))
        for raw in [b'not-json', b'[]', b'{"messages":null}']:
            with self.assertRaises(guard.BoundedVisualRequestError): guard.inspect_payload(raw)

    def test_final_send_dynamic_registry_and_no_mutation(self):
        part, sha = fixture(3000, 1200)
        registry = set()
        raw = body([part]) + b'\n '
        seen = []
        def original(client, request):
            seen.append(request.content)
            return httpx.Response(200, request=request, json={'fixture': True})
        with tempfile.TemporaryDirectory() as tmp, patch.object(httpx.Client, '_send_single_request', original):
            logfile = Path(tmp) / 'guard.jsonl'
            guard.install(logfile, rendered_registry=lambda: registry)
            with httpx.Client(trust_env=False) as client:
                request = httpx.Request('POST', 'https://fixture.invalid/v1/chat/completions', content=raw,
                                        headers={'Authorization': 'secret-must-not-be-logged'})
                self.assertEqual(client.send(request).status_code, 200)
                registry.add(sha)
                with self.assertRaises(guard.BoundedVisualRequestError): client.send(request)
            self.assertEqual(seen, [raw])
            logs = [json.loads(x) for x in logfile.read_text().splitlines()]
            self.assertEqual([x['decision'] for x in logs], ['allow', 'reject'])
            self.assertNotIn('secret-must-not-be-logged', logfile.read_text())
            self.assertNotIn('data:image', logfile.read_text())
            self.assertFalse(logs[1]['network_send_authorized'])

    def test_noncompletion_requests_untouched_and_wrong_method_blocked(self):
        seen = []
        def original(client, request):
            seen.append(request.url.path)
            return httpx.Response(200, request=request)
        with tempfile.TemporaryDirectory() as tmp, patch.object(httpx.Client, '_send_single_request', original):
            log = Path(tmp) / 'ledger.jsonl'
            guard.install(log, rendered_registry=set())
            with httpx.Client(trust_env=False) as client:
                client.get('https://fixture.invalid/fetch')
                self.assertFalse(log.exists())
                with self.assertRaises(guard.BoundedVisualRequestError):
                    client.get('https://fixture.invalid/v1/chat/completions')
            self.assertEqual(seen, ['/fetch'])

    def test_ledger_failure_prevents_network(self):
        seen = []
        def original(client, request): seen.append(True)
        with tempfile.TemporaryDirectory() as tmp, patch.object(httpx.Client, '_send_single_request', original):
            report = Path(tmp) / 'is-directory'; report.mkdir()
            guard.install(report, rendered_registry=set())
            with httpx.Client(trust_env=False) as client:
                with self.assertRaises(IsADirectoryError):
                    client.post('https://fixture.invalid/v1/chat/completions', content=body([]))
            self.assertFalse(seen)

    def test_registry_failure_prevents_network(self):
        def broken(): raise OSError('private error detail')
        with self.assertRaises(guard.BoundedVisualRequestError) as caught:
            guard.inspect_payload(body([]), rendered_registry=broken, strict_all_images=False)
        self.assertNotIn('private', str(caught.exception))


if __name__ == '__main__': unittest.main()
