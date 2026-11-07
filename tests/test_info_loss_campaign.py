import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from info_loss_campaign import recover

class SpanGateTests(unittest.TestCase):
    def fixture(self):
        events=[]
        for i in range(3):events.append({'type':'tool/result','seq':i+1,'data':{'step':i+1,'message':{'role':'tool','content':[{'type':'text','text':f'Fact {i}'}]}}})
        events.append({'type':'compaction/summary','data':{'shadowedSeqs':[1,2,3],'summary':[]}})
        chars=sum(len(str(e['data']['message']['content'])) for e in events[:-1])
        render={'font_size':16,'history_scale':1,'native_image_ids':[],'stats':{'messages_rendered':3,'text_chars':chars}}
        return events,render
    def test_exact_seq_selection_ignores_uncompressed_tail(self):
        e,r=self.fixture();e.append({'type':'tool/result','seq':99,'data':{'step':99,'message':{'role':'tool','content':[{'type':'text','text':'TAIL SECRET'}]}}})
        result=recover(e,r);self.assertNotIn('TAIL SECRET',result['source']);self.assertEqual(result['shadowed_seqs'],[1,2,3])
    def test_mismatch_and_missing_sequence_block_paid_gate(self):
        e,r=self.fixture();r['stats']['text_chars']+=1
        with self.assertRaises(ValueError):recover(e,r)
        e,r=self.fixture();e[3]['data']['shadowedSeqs'].append(999)
        with self.assertRaises(ValueError):recover(e,r)
    def test_native_images_are_not_silently_language_encoded(self):
        e,r=self.fixture();e[0]['data']['message']['content'].append({'type':'image'})
        with self.assertRaises(ValueError):recover(e,r)
if __name__=='__main__':unittest.main()
