import base64, hashlib, io, json, sys, unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import inline_visual_transport_v1 as transport

class PageBudgetTests(unittest.TestCase):
    def fixture(self, natives=2):
        content=[{'type':'text','text':'Exact context'}]; registry=set(); ordinal=0
        for segment,count in [('History',8),('Recent',6),('native',natives)]:
            for i in range(count):
                raw=io.BytesIO();Image.new('RGB',(16,16),(ordinal,0,0)).save(raw,format='PNG');ordinal+=1
                raw=raw.getvalue()
                if segment!='native':
                    registry.add(hashlib.sha256(raw).hexdigest())
                    content.append({'type':'text','text':f'[{segment} page {i+1}/{count} — linear scale 1, high detail]'})
                content.append({'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(raw).decode(),'detail':'high'}})
        return json.dumps({'messages':[{'role':'user','content':content}]}).encode(),registry

    def test_segments_independent_native_preserved_and_pixels_unchanged(self):
        body,registry=self.fixture(); wire,row=transport.transform(body,rendered_registry=registry,page_budget={'history':5,'recent':2})
        parts=json.loads(wire)['messages'][0]['content']; original=json.loads(body)['messages'][0]['content']
        labels=[p['text'] for p in parts if p['type']=='text']
        self.assertEqual(len([t for t in labels if t.startswith('[History')]),5)
        self.assertEqual(len([t for t in labels if t.startswith('[Recent')]),2)
        self.assertIn('[History page 4/8 — linear scale 1, high detail]',labels)
        self.assertIn('[Recent page 5/6 — linear scale 1, high detail]',labels)
        self.assertEqual(parts[-2:],original[-2:])
        self.assertTrue(all(p in original for p in parts))
        self.assertEqual(row['image_count'],9)
        self.assertEqual(row['version'],'inline-history5-recent2-v1')
        audit=row['selection']['canvas_page_selection']
        self.assertEqual(audit['generated_counts'],{'history':8,'recent':6})
        self.assertEqual(audit['retained_counts'],{'history':5,'recent':2})
        self.assertEqual(len(audit['removed']),7)
        self.assertFalse(audit['evidence_complete'])
        self.assertEqual(row['selection']['removed'],[])

    def test_overall_limit_rejects_instead_of_deleting_native(self):
        body,registry=self.fixture(natives=11)
        with self.assertRaisesRegex(ValueError,'refusing native'):
            transport.transform(body,rendered_registry=registry,page_budget={'history':5,'recent':2})

    def test_unlabeled_canvas_rejected(self):
        body,registry=self.fixture(); data=json.loads(body)
        data['messages'][0]['content'][1]['text']='unidentified canvas'
        with self.assertRaisesRegex(ValueError,'segment label'):
            transport.transform(json.dumps(data).encode(),rendered_registry=registry,page_budget={'history':5,'recent':2})

    def test_sdk_combined_prompt_and_label_preserves_prompt(self):
        body,registry=self.fixture();data=json.loads(body)
        data['messages'][0]['content'][1]['text']='Preserve this memory instruction\n'+data['messages'][0]['content'][1]['text']
        wire,_=transport.transform(json.dumps(data).encode(),rendered_registry=registry,page_budget={'history':5,'recent':2})
        self.assertEqual(json.loads(wire)['messages'][0]['content'][1]['text'],'Preserve this memory instruction\n')

    def test_native_capacity_reduces_history_before_recent(self):
        body,registry=self.fixture(natives=4)
        _,row=transport.transform(body,rendered_registry=registry,page_budget={'history':5,'recent':2})
        self.assertEqual(row['image_count'],10)
        self.assertEqual(row['selection']['canvas_page_selection']['retained_counts'],{'history':4,'recent':2})
