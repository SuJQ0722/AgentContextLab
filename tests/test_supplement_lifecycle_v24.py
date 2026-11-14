import json,sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import lifecycle_supplement_v24 as life

class LifecycleTests(unittest.TestCase):
    def run_fixture(self,finished,cleanup,uid='bound',live=True):
        jobs=[{'job_id':f'{s}-{i}','scope':s,'shard':i}for s in ('core','controlled')for i in range(3)]
        def read(path):
            name=Path(path).name
            if name=='plan.json':return {'jobs':jobs}
            if name=='status.json':return {'finished':finished,'active':0 if finished else 1,'pending':0,'unknown':[]}
            if name=='result.json':return {'slot_released':cleanup}
            if name=='binding.json':return {'uid':'bound'}
            raise AssertionError(name)
        def exists(path):return Path(path).name=='status.json'
        def describe(name):return {'returncode':0,'stdout':json.dumps({'name':name,'uid':uid,'state':'RUNNING'})}
        with patch.object(life,'read',read),patch.object(Path,'exists',exists),patch.object(life,'save'),patch.object(life,'immutable'),patch.object(life,'describe',side_effect=describe)as query,patch.object(life,'create_cli',return_value={'returncode':0})as stop:
            try:result=life.cycle(live)
            except ValueError:
                self.assertEqual(stop.call_count,0);raise
            return result,query.call_count,stop.call_count

    def test_active_nodes_are_never_stopped(self):
        self.assertEqual(self.run_fixture(False,True),(False,0,0))
    def test_orphan_uncertainty_prevents_stopping(self):
        self.assertEqual(self.run_fixture(True,False),(False,0,0))
    def test_bound_drained_nodes_can_stop(self):
        self.assertEqual(self.run_fixture(True,True),(True,6,6))
    def test_different_cloud_identity_is_not_stopped(self):
        with self.assertRaises(ValueError):self.run_fixture(True,True,uid='different')
