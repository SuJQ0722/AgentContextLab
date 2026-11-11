import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import watch_visual_inline_resources_v7 as observer


class ObserverTests(unittest.TestCase):
    def test_heartbeat_and_terminal_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);controller=root/'controllers/hermes/a';controller.mkdir(parents=True)
            (controller/'status.json').write_text(json.dumps({'pid':12,'active_local':16,'target_concurrency':16,'heartbeat_unix':20}))
            with patch.object(observer,'load_cells',return_value=({'x':{'root':root,'plan':{'jobs':[1,2]}}},{})):
                row=observer.controller_status(root)['x']
                self.assertEqual(row['planned'],2);self.assertEqual(row['controllers'][0]['active_local'],16)
                self.assertEqual(row['controllers'][0]['exit'],{})
                (controller/'exit.json').write_text(json.dumps({'drained':True}))
                self.assertTrue(observer.controller_status(root)['x']['controllers'][0]['exit']['drained'])
    def test_finished_grader_exits_without_process_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'root';root.mkdir();out=Path(tmp)/'out';out.mkdir()
            (out/'status.json').write_text(json.dumps({'finished':True,'all_terminal':True}))
            with patch.object(sys,'argv',['observer','--root',str(root),'--output',str(out)]),patch.object(observer,'refresh_once',return_value=(True,{})),patch.object(observer,'controller_status',return_value={}),patch.object(observer.signal,'signal'):
                observer.main()
            result=json.loads((out/'v7-observer-exit.json').read_text())
            self.assertEqual(result['reason'],'all_predictions_terminal_and_private_grader_finished')
            self.assertFalse(result['native_signaled'])


if __name__=='__main__':unittest.main()
