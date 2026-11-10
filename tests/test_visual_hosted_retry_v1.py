import json,tempfile,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from prepare_visual_hosted_retry_v1 import select
class Selection(unittest.TestCase):
 def fixture(self,root,name,status,clean=True):
  p=Path(root)/name;p.mkdir();(p/'result.json').write_text(json.dumps({'status':status,'slot_released':clean,'unconfirmed_child_termination':[]}));return p
 def test_any_completed_kept_regardless_later_failure(self):
  with tempfile.TemporaryDirectory()as d:
   a=self.fixture(d,'old','completed');b=self.fixture(d,'new','timeout');selected,records=select([a,b]);self.assertFalse(selected);self.assertEqual(len(records),2)
 def test_failure_only_selected_and_duplicate_lineage_dedup(self):
  with tempfile.TemporaryDirectory()as d:
   a=self.fixture(d,'old','failed');b=self.fixture(d,'new','timeout');yes,records=select([a,a,b]);self.assertTrue(yes);self.assertEqual(len(records),2)
 def test_unknown_cleanup_and_interrupted_blocked(self):
  with tempfile.TemporaryDirectory()as d:
   a=self.fixture(d,'old','timeout',False)
   with self.assertRaises(ValueError):select([a])
   b=self.fixture(d,'other','interrupted')
   with self.assertRaises(ValueError):select([b])
if __name__=='__main__':unittest.main()
