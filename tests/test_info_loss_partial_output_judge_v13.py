import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_partial_output_judge_v13 as partial
class PartialJudgeTests(unittest.TestCase):
 def test_prompt_exactly_matches_original_stop_judge(self):
  facts=[{'id':'f1','question':'Which value?','answer':'42','quote':'value 42'}];captured=[]
  class Client:
   def call(self,key,prompt,images=(),purpose='evaluation'):
    if key.endswith('_qa'):return {'status':'completed','finish_reason':'stop','content':json.dumps({'f1':'42'})}
    if key.endswith('_reconstruction'):return {'status':'completed','finish_reason':'stop','content':'value 42'}
    captured.append(prompt);return {'status':'completed','finish_reason':'stop','content':json.dumps({'facts':{'f1':{'supported':True,'evidence':'value 42'}}})}
  partial.base.phase.condition(Client(),{'id':'q_009'},{'text_control':{'text':'source'}},facts,'tiles_high','text_control')
  self.assertEqual(captured,[partial.judge_prompt(facts,'value 42')])
 def test_key_does_not_change_condition(self):
  key='tiles_high_q_009_canvas_0.75_reconstruction';parts=key.split('_');self.assertEqual('_'.join(parts[2:4]),'q_009');self.assertEqual('_'.join(parts[4:-1]),'canvas_0.75')
if __name__=='__main__':unittest.main()
