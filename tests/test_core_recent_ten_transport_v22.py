"""Offline tests for explicit core retention versus strict native controls."""
import base64
import copy
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
import core_recent_ten_transport_v22 as core
import dsh_core_recent_ten_v22 as dsh
import inline_visual_transport_v1 as frozen


def picture(i):
    out = io.BytesIO()
    Image.new('RGB', (12, 20), (i, 23, 51)).save(out, format='PNG')
    raw = out.getvalue()
    return {'type':'image_url', 'image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode(), 'detail':'high'}}, hashlib.sha256(raw).hexdigest()


def fixture(native=0, history=0, recent=0, dsh_handles=False):
    parts = [{'type':'text','text':'question text remains'}]
    registry = set()
    counter = 0
    for i in range(native):
        part, sha = picture(counter); counter += 1
        parts.extend([{'type':'text','text':f'native evidence {i}'},part])
    for segment, count in [('History',history),('Recent',recent)]:
        for i in range(count):
            part, sha = picture(counter); counter += 1; registry.add(sha)
            parts.append({'type':'text','text':f'[{segment} page {i+1}/{count} — linear scale 0.75, high detail]'})
            if dsh_handles:
                parts.append({'type':'text','text':f'Image sha256:{sha}; request preview 12x20px. It may be resized or re-encoded; source dimensions, format, and byte size may differ.'})
            parts.append(part)
    payload = {'model':'offline', 'messages':[{'role':'system','content':'stable system'}, {'role':'user','content':parts},
                                            {'role':'assistant','tool_calls':[{'id':'t','type':'function','function':{'name':'search','arguments':'{}'}}]},
                                            {'role':'tool','tool_call_id':'t','content':'stable tool'}]}
    return payload, registry


def run(payload, registry, **kwargs):
    return core.transform(json.dumps(payload).encode(), rendered_registry=registry, policy='core_recent10',
                          page_budget={'history':5,'recent':2}, **kwargs)


class CoreRetentionTests(unittest.TestCase):
    def test_fourteen_native_before_compression_last_ten_exact(self):
        payload, registry = fixture(native=14)
        before = copy.deepcopy(payload)
        original = [p for p in payload['messages'][1]['content'] if p['type']=='image_url']
        with self.assertRaisesRegex(ValueError, 'Native images exceed'):
            frozen.transform(json.dumps(payload).encode(), rendered_registry=registry, page_budget={'history':5,'recent':2})
        wire, audit = run(payload, registry)
        after = json.loads(wire)
        self.assertEqual([p for p in after['messages'][1]['content'] if p['type']=='image_url'],original[-10:])
        self.assertEqual(payload,before)
        self.assertEqual(after['messages'][2:],payload['messages'][2:])
        self.assertEqual([p for p in after['messages'][1]['content'] if p['type']=='text'],[p for p in before['messages'][1]['content'] if p['type']=='text'])
        self.assertEqual(audit['native_images_removed'],4)
        self.assertEqual([r['original_image_ordinal'] for r in audit['removed_original_images']],list(range(4)))
        self.assertFalse(audit['native_evidence_preserved'])
        self.assertEqual(audit['hosting_calls'],0)

    def test_caps_then_last_ten_with_original_offset_provenance(self):
        payload, registry = fixture(native=4,history=7,recent=3)
        wire,audit = run(payload,registry)
        self.assertEqual(audit['image_count'],10)
        self.assertEqual(audit['final_canvas_counts'],{'history':5,'recent':2})
        removed=audit['removed_original_images']
        self.assertEqual([r['original_image_ordinal'] for r in removed],[0,4,5,11])
        self.assertEqual([r['reason'] for r in removed],['global_last10','canvas_segment_cap','canvas_segment_cap','canvas_segment_cap'])
        self.assertEqual([r['original_image_ordinal'] for r in audit['retained_original_images']],[1,2,3,6,7,8,9,10,12,13])
        for r in removed:
            part=payload['messages'][r['message_index']]['content'][r['original_part_index']]
            self.assertEqual(hashlib.sha256(base64.b64decode(part['image_url']['url'].split(',')[1])).hexdigest(),r['sha256'])

    def test_core_allows_native_fourteen_even_with_canvas(self):
        payload,registry=fixture(native=14,history=5,recent=2)
        _,audit=run(payload,registry)
        self.assertEqual(audit['image_count'],10)
        self.assertEqual(audit['native_images_removed'],11)
        self.assertEqual(audit['final_canvas_counts'],{'history':5,'recent':2})

    def test_last_ten_is_occurrence_order_not_unique_sha(self):
        payload,registry=fixture(native=1)
        part=payload['messages'][1]['content'][-1]
        payload['messages'][1]['content']=[copy.deepcopy(part) for _ in range(14)]
        _,audit=run(payload,registry)
        self.assertEqual([r['original_image_ordinal'] for r in audit['retained_original_images']],list(range(4,14)))

    def test_strict_native_does_not_silently_drop_eleven(self):
        for caps in [None,{'history':5,'recent':2}]:
            payload,registry=fixture(native=11)
            with self.assertRaisesRegex(ValueError,'Strict native evidence exceeds'):
                core.transform(json.dumps(payload).encode(),rendered_registry=registry,policy='strict_native',page_budget=caps)

    def test_strict_native_reserves_all_native_before_canvas(self):
        payload,registry=fixture(native=4,history=5,recent=2)
        wire,audit=core.transform(json.dumps(payload).encode(),rendered_registry=registry,policy='strict_native',page_budget={'history':5,'recent':2})
        self.assertEqual(audit['image_count'],10)
        self.assertEqual(sum(r['origin']=='native' for r in audit['selection']['retained']),4)
        self.assertTrue(audit['native_evidence_preserved'])

    def test_unmodified_body_keeps_exact_serialization(self):
        payload,registry=fixture(native=3,history=5,recent=2)
        raw=json.dumps(payload,indent=3).encode()
        wire,audit=core.transform(raw,rendered_registry=registry,policy='core_recent10',page_budget={'history':5,'recent':2})
        self.assertEqual(wire,raw)
        self.assertEqual(audit['removed_original_images'],[])

    def test_dsh_verified_handles_and_caps(self):
        payload,registry=fixture(native=14,history=7,recent=3,dsh_handles=True)
        wire,audit=dsh.transform(json.dumps(payload).encode(),rendered_registry=registry,policy='core_recent10',page_budget={'history':5,'recent':2})
        self.assertEqual(audit['image_count'],10)
        self.assertEqual(audit['final_canvas_counts'],{'history':5,'recent':2})
        self.assertEqual(audit['harness'],'dsh')
        self.assertEqual(sum(p.get('type')=='text' and p.get('text','').startswith('Image sha256:') for p in json.loads(wire)['messages'][1]['content']),7)

    def test_invalid_handle_cannot_mask_unverified_canvas_label(self):
        payload,registry=fixture(history=1,dsh_handles=True)
        payload['messages'][1]['content'][2]['text']='unrelated text'
        with self.assertRaisesRegex(ValueError,'verified segment label'):
            dsh.transform(json.dumps(payload).encode(),rendered_registry=registry,policy='core_recent10',page_budget={'history':5,'recent':2})

    def test_policy_must_be_explicit_and_envelope_fixed(self):
        payload,registry=fixture(native=1)
        for kw in [{'policy':'implicit'},{'policy':'core_recent10','max_images':11},{'policy':'core_recent10','page_budget':{'history':6,'recent':2}}]:
            with self.assertRaises(ValueError): core.transform(json.dumps(payload).encode(),rendered_registry=registry,**kw)

    def test_install_forwards_only_transformed_body_and_restores(self):
        payload,registry=fixture(native=14)
        sent=[]
        def fake(client,request):
            sent.append(json.loads(request.content))
            return httpx.Response(200,json={'ok':True},request=request)
        with tempfile.TemporaryDirectory() as td, patch.object(httpx.Client,'_send_single_request',fake):
            handle=core.install(td,rendered_registry=registry,approved_base_url='http://offline.invalid',policy='core_recent10',page_budget={'history':5,'recent':2})
            try:
                with httpx.Client() as client:
                    response=client.post('http://offline.invalid/chat/completions',json=payload)
                    self.assertEqual(response.status_code,200)
                with self.assertRaises(RuntimeError): core.install(td,rendered_registry=registry,approved_base_url='http://offline.invalid',policy='core_recent10')
            finally:handle['uninstall']()
            self.assertIs(httpx.Client._send_single_request,fake)
            rows=[json.loads(x) for x in Path(handle['ledger']).read_text().splitlines()]
            self.assertEqual(rows[0]['native_images_removed'],4)
            self.assertTrue(rows[0]['network_send_authorized'])
        self.assertEqual(sum(p.get('type')=='image_url' for p in sent[0]['messages'][1]['content']),10)

if __name__=='__main__':unittest.main()
