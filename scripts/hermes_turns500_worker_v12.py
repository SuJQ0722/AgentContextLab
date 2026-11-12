"""Verify the actual Hermes AIAgent constructor and record its runtime turn limit."""
import argparse,builtins,json
from pathlib import Path
from unittest.mock import patch
from turns500_contract_v12 import validate,VERSION

def checked_init(original, output):
    def init(self,*args,**kwargs):
        if kwargs.get('max_iterations')!=500 or type(kwargs.get('max_iterations')) is not int:
            raise ValueError('Actual Hermes constructor must receive max_iterations=500')
        result=original(self,*args,**kwargs)
        if getattr(self,'max_iterations',None)!=500:raise ValueError('Actual Hermes turn limit differs')
        path=Path(output)/'metrics/turn-limit-binding-v12.json';path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps({'version':VERSION,'harness':'hermes','constructor_max_iterations':500,
                                  'actual_agent_max_iterations':self.max_iterations,'model_calls_by_observer':0}))
        return result
    return init

def main():
    p=argparse.ArgumentParser(add_help=False);p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a,_=p.parse_known_args()
    spec=json.loads(a.spec.read_text());validate(spec,json.loads(Path(spec['config_path']).read_text()))
    if spec['strategy']=='visual':import hermes_canvas_budget_worker_v11 as worker
    else:import hermes_baseline_retry3_v10 as worker
    original_import=builtins.__import__;restores=[]
    def importing(name,globals=None,locals=None,fromlist=(),level=0):
        module=original_import(name,globals,locals,fromlist,level)
        if name=='run_agent' and 'AIAgent' in (fromlist or ()) and not restores:
            cls=module.AIAgent;old=cls.__init__;cls.__init__=checked_init(old,a.out);restores.append((cls,old))
        return module
    try:
        with patch.object(builtins,'__import__',importing):worker.main()
    finally:
        for cls,old in restores:cls.__init__=old

if __name__=='__main__':main()
