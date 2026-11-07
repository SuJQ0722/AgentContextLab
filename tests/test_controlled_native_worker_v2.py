import base64,copy,io,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from controlled_native_worker_v2 import compose,native_parts,BudgetInfeasible
from controlled_native_preflight import image_ids,text_only

class ControlledContinuationTests(unittest.TestCase):
    def test_preserve_original_native_and_later_tool_messages(self):
        image={'type':'image_url','image_url':{'url':'data:image/png;base64,AAAA','detail':'high'}}
        current=[{'role':'system','content':'system'}, {'role':'user','content':[image]},
                 {'role':'assistant','tool_calls':[{'id':'x'}]}, {'role':'tool','content':'new tool evidence','tool_call_id':'x'}]
        before=copy.deepcopy(current);messages=compose(current,'question',[image],[{'type':'text','text':'summary'}])
        self.assertEqual(messages[-2:],current[-2:]);self.assertEqual(current,before)
        self.assertEqual(image_ids(native_parts(messages)),image_ids([image]))
        self.assertNotIn('base64',str(text_only(messages)))
    def test_unfrozen_native_evidence_rejected(self):
        with self.assertRaises(BudgetInfeasible):native_parts([{'role':'user','content':[{'type':'image_url','image_url':{'url':'https://example.org/a.png'}}]}])
