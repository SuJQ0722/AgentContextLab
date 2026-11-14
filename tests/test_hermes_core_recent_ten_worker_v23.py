"""Fresh wrapper binding preserves frozen entry chain without model calls."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import hermes_core_recent_ten_worker_v23 as worker
import core_recent_ten_transport_v22 as core
import hermes_canvas_budget_worker_v11 as budget
import hermes_visual_inline_retry_worker_v4 as visual
import inline_visual_transport_v1 as frozen
from test_core_recent_ten_transport_v22 import fixture


def documents(config_path):
    policy={'native_image_policy':'core_recent10','core_transport_version':core.VERSION,
            'runtime_recovery_version':budget.VERSION,
            'visual_image_retention':{'max_images_per_request':10,'page_budget':{'history':5,'recent':2},'max_request_bytes':32*1024*1024}}
    spec=dict(policy,config_path=str(config_path),harness='hermes',strategy='visual',experiment_kind='mmbc')
    return spec,policy


class CoreWorkerBindingTests(unittest.TestCase):
    def test_requires_both_documents_and_rejects_controlled_scope(self):
        spec,cfg=documents('unused')
        worker.validate(spec,cfg)
        for field,value in [('native_image_policy',None),('core_transport_version','old'),('controlled_spec_path','controlled.json'),('calibration_not_scored',True)]:
            for side in (0,1):
                pair=[copy.deepcopy(spec),copy.deepcopy(cfg)];pair[side][field]=value
                with self.assertRaises(ValueError):worker.validate(*pair)
        with self.assertRaises(ValueError):worker.validate(spec|{'experiment_kind':'controlled'},cfg)

    def test_full_frozen_binding_does_not_recurse_or_lie_about_native_removal(self):
        payload,registry=fixture(native=14)
        body=json.dumps(payload).encode();seen=[]
        original_transform=frozen.transform;original_budget=budget.transform
        original_version=frozen.transport_version
        def inherited_visual_main():
            wire,audit=frozen.transform(body,rendered_registry=registry,max_images=10,page_budget={'history':5,'recent':2},max_body_bytes=32*1024*1024)
            seen.append(audit)
            self.assertEqual(audit['version'],core.VERSION)
            self.assertTrue(audit['canvas_budget_recovery']['native_evidence_modified'])
            self.assertEqual(audit['native_images_removed'],4)
            self.assertEqual(visual.transport_version(10,{'history':5,'recent':2}),core.VERSION)
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);spec,cfg=documents(root/'config.json')
            (root/'config.json').write_text(json.dumps(cfg));(root/'spec.json').write_text(json.dumps(spec))
            argv=['worker','--spec',str(root/'spec.json'),'--out',str(root/'out')]
            # Keep the actual frozen canvas wrapper; replace only model-loop
            # endpoint and outer turn constructor entry with offline callbacks.
            with patch.object(sys,'argv',argv), patch.object(worker.turns_worker,'main',budget.main) as entry, patch.object(visual,'main',inherited_visual_main):
                worker.main()
            binding=json.loads((root/'out/metrics/core-image-policy-binding-v23.json').read_text())
            self.assertEqual(binding['actual_wire_ledger'],'metrics/inline-images-wire-v1.jsonl')
            self.assertEqual(binding['wire_schema_version'],core.VERSION)
            self.assertEqual(binding['turn_limit_entry'],'hermes_turns500_worker_v12')
        self.assertEqual(len(seen),1)
        self.assertIs(frozen.transform,original_transform)
        self.assertIs(budget.transform,original_budget)
        self.assertIs(frozen.transport_version,original_version)

    def test_rejected_policy_never_enters_original_worker(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);spec,cfg=documents(root/'config.json');spec['native_image_policy']='strict_native'
            (root/'config.json').write_text(json.dumps(cfg));(root/'spec.json').write_text(json.dumps(spec))
            with patch.object(sys,'argv',['worker','--spec',str(root/'spec.json'),'--out',str(root/'out')]),patch.object(worker.turns_worker,'main') as inherited:
                with self.assertRaises(ValueError):worker.main()
                inherited.assert_not_called()

if __name__=='__main__':unittest.main()
