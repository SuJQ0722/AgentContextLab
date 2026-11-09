from pathlib import Path
import base64,hashlib,io,json,sys,tempfile,unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import info_loss_phase3 as study

class InformationLossTests(unittest.TestCase):
    def journal(self,folder):
        image=Image.new('RGB',(40,80),(230,240,250));buffer=io.BytesIO();image.save(buffer,format='PNG');blob=buffer.getvalue();digest=hashlib.sha256(blob).hexdigest()
        history=[{'role':'tool','content':f'Page {n}: Harbor vessel carried {n+70} passengers.'} for n in range(3)]
        value={'state':{'engine':{'compression_count':1,'_full_history':history}},'compression_count_delta':1,
            'render_stats':{'messages_rendered':3,'renderer_version':'multimodal-wrap-v2','source_image_occurrences':0,'source_image_coverage_verified':True,'image_count':1},
            'policy_config':{'model':'source','strategy_config':{'font_size':16,'history_scale':1}},'call_id':'first',
            'image_ledger':[{'message_index':0,'content_index':0,'source_sha256':digest,'native_attachment':{'attachmentId':'sha256:'+digest,'width':40,'height':80}}],
            'output':[{'content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(blob).decode(),'detail':'high'}}]}]}
        path=folder/'journal.json';path.write_text(json.dumps(value));return path,value,blob

    def test_exact_renderer_source_and_complete_image_preserved_across_scales(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path,value,blob=self.journal(root);case=study.freeze_case(path,root/'out','q1')
            self.assertEqual(case['rendered_message_count'],3)
            self.assertEqual(Path(case['representations']['canvas_1']['images'][0]['path']).read_bytes(),blob)
            dims=[(case['representations'][m]['images'][0]['width'],case['representations'][m]['images'][0]['height']) for m in ['canvas_1','canvas_0.75','canvas_0.5']]
            self.assertEqual(dims,[(40,80),(30,60),(20,40)])
            self.assertEqual([p['message_index'] for p in case['fact_positions']],[0,1,2])
            self.assertIn('72 passengers',Path(case['source_path']).read_text())

    def test_unmatched_source_and_native_image_history_rejected_before_calls(self):
        for change in ['count','native','imagehash']:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);path,value,blob=self.journal(root)
                if change=='count':value['render_stats']['messages_rendered']=2
                elif change=='native':value['render_stats']['source_image_occurrences']=1
                else:value['image_ledger'][0]['source_sha256']='f'*64
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):study.freeze_case(path,root/'out','q1')

    def test_facts_grounded_and_question_answer_leak_rejected(self):
        fact={'type':'number','answer':'71','quote':'71 passengers','question':'How many passengers did the vessel carry?'}
        self.assertEqual(len(study.grounded_facts({'facts':[fact]},'71 passengers')),1)
        self.assertEqual(study.grounded_facts({'facts':[{**fact,'question':'Was it 71 passengers?'}]},'71 passengers'),[])
        self.assertEqual(study.grounded_facts({'facts':[None,42,{'answer':71}]},'71 passengers'),[])

    def test_semantic_judge_requires_evidence_from_reconstruction_not_substring_alone(self):
        facts=[{'id':'f1','answer':'71'}]
        response={'status':'completed','finish_reason':'stop','content':json.dumps({'facts':{'f1':{'supported':True,'evidence':'71 passengers'}}})}
        self.assertIsNotNone(study.reconstruction_judgment(response,facts,'There were 71 passengers.'))
        self.assertIsNone(study.reconstruction_judgment(response,facts,'A ship was built in 1871.'))
        response['content']='{"facts":[]}'
        self.assertIsNone(study.reconstruction_judgment(response,facts,'71'))

    def test_common_denominator_retains_missing_condition_bounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'facts').mkdir();(root/'facts/q1.json').write_text(json.dumps([{'id':'f1'},{'id':'f2'}]))
            manifest={'cases':[{'id':'q1'}],'limitations':[],'max_requests':19}
            row={'case':'q1','method':'text_control','fact_count':2,'qa_exact_correct':1,'semantic_supported_facts':1}
            report=study.report(root,manifest,'running',[row]);table={r['method']:r for r in report['summary']}
            self.assertEqual(table['text_control']['qa_accuracy_bounds'],[.5,.5])
            self.assertEqual(table['canvas_1']['qa_accuracy_bounds'],[0,1])
            self.assertEqual(table['canvas_1']['shared_fact_denominator'],2)
            self.assertEqual(report['paired_complete_cases'],[])

if __name__=='__main__':unittest.main()
