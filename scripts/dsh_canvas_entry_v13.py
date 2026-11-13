"""Propagate one independent DSH bridge repair through Python child entrypoints.

Invoke under network_entry_v13.py. It remains the owner of network credentials.
"""
import sys,subprocess,runpy
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ENTRY=Path(__file__).resolve()

def main():
    if len(sys.argv)<3 or sys.argv[1]!='--target':raise SystemExit('Expected --target script.py')
    target=Path(sys.argv[2]).resolve();argv=sys.argv[3:]
    if target.name=='run_turns500_trial_v12.py':target=ROOT/'scripts/dsh_canvas_trial_v13.py'
    original=subprocess.Popen
    class Propagate(original):
        def __init__(self,args,*a,**kw):
            command=list(args)if isinstance(args,(list,tuple))else args
            if isinstance(command,list)and len(command)>1 and 'python'in Path(str(command[0])).name:
                p=Path(str(command[1]))
                if p.suffix=='.py'and p.resolve()!=ENTRY and p.name!='network_entry_v13.py':command=[command[0],str(ENTRY),'--target',str(p),*command[2:]]
            super().__init__(command,*a,**kw)
    subprocess.Popen=Propagate
    sys.argv=[str(target),*argv]
    runpy.run_path(str(target),run_name='__main__')
if __name__=='__main__':main()
