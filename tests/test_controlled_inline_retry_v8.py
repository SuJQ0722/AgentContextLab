import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import controlled_inline_retry_v8 as worker
from controlled_native_worker_v5 import compose, native_parts, image_ids


def image(value):
    return {'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(value.encode()).decode(),'detail':'high'}}


class ControlledRetryTests(unittest.TestCase):
    def test_trim_only_canvas_keep_native_bytes_and_positions(self):
        native=[image('native1'),image('native2')];pages=[image('page'+str(i)) for i in range(13)]
        messages=[{'role':'system','content':'system'},{'role':'user','content':'old'},{'role':'assistant','content':'later'}]
        original=copy.deepcopy((native,pages,messages))
        with tempfile.TemporaryDirectory() as directory:
            actual=worker.native_last_compose(compose,Path(directory),messages,'question',native,pages)
            content=actual[1]['content'];self.assertEqual(content[-2:],native)
            self.assertEqual(content[1:-2],pages[-8:]);self.assertEqual(len(native_parts(actual)),10)
            self.assertEqual((native,pages,messages),original)
            record=json.loads((Path(directory)/'controlled-retention.jsonl').read_text())
            self.assertEqual(record['native_images_removed'],0);self.assertEqual(record['removed_canvas_ordinals'],[0,1,2,3,4])
            inspect=worker.native_first_inspection(native_parts,image_ids(native))
            self.assertEqual(image_ids(inspect(actual)[:2]),image_ids(native))

    def test_text_arms_native_last_and_oversized_native_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            actual=worker.native_last_compose(compose,Path(directory),[],'q',[image('native')],[{'type':'text','text':'summary'}])
            self.assertEqual(actual[0]['content'][1]['text'],'summary')
            self.assertEqual(actual[0]['content'][-1],image('native'))
            with self.assertRaisesRegex(ValueError,'Native evidence alone'):
                worker.native_last_compose(compose,Path(directory),[],'q',[image(str(i)) for i in range(11)],[])

    def test_first_valid_target_immutable_no_answer_condition(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);job={'campaign_root':directory,'job_id':'ds/q1/visual','controlled_method':'visual','control_target_path':str(worker.target_path(root,'ds/q1'))}
            state={'passed':True,'method':'visual','native_identity_verified':True,'final_wire_native_identity_preserved':True,'final_wire_observed':True,'bounded_native_protocol':worker.bounded.PROTOCOL,'first_actual_prompt_tokens':8000,'native_hashes':['fixture'],'prefix_sha256':'prefix'}
            bad={**state,'final_wire_native_identity_preserved':False}
            self.assertFalse(worker.publish_target(job,bad));self.assertFalse(Path(job['control_target_path']).exists())
            self.assertTrue(worker.publish_target(job,state))
            self.assertFalse(worker.publish_target(job,{**state,'first_actual_prompt_tokens':9000}))
            self.assertEqual(json.loads(Path(job['control_target_path']).read_text())['first_actual_prompt_tokens'],8000)
            with self.assertRaisesRegex(ValueError,'scientific identity'):
                worker.publish_target(job,{**state,'native_hashes':['changed']})
