"""Cross-experiment process admission; reserve child-process growth before spawning."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time
from lab import ROOT
from run_bc_trial import atomic,process_identity

STATE=ROOT/'outputs/supervision'
LIMIT=127  # user requires strictly fewer than128 visible processes
CORE_WORKERS=16
CORE_COST=5  # trial supervisor + native worker + possible render subprocesses
MARGIN=4    # shells, monitoring and transient administrative work

def processes():
    result={}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        try:
            fields=(p/'stat').read_text().split(') ',1)[1].split()
            argv=[v.decode(errors='replace') for v in (p/'cmdline').read_bytes().split(b'\0') if v]
            cmd=' '.join(argv)
            result[int(p.name)]={'ppid':int(fields[1]),'identity':fields[19],'cmd':cmd,'argv':argv}
        except (FileNotFoundError,ProcessLookupError,PermissionError):continue
    return result

def is_worker(record,script):
    argv=record.get('argv',[])
    # Interpreter invocation only; never match shell/-c source text substrings.
    return len(argv)>1 and Path(argv[1]).name==script


def descendants(pid,snapshot):
    seen={pid};changed=True
    while changed:
        extra={p for p,r in snapshot.items() if r['ppid'] in seen}-seen
        changed=bool(extra);seen.update(extra)
    return seen & set(snapshot)

def capacity(snapshot,reservations,cost):
    """Pure conservative projection; include all visible processes, including zombies."""
    core=[p for p,r in snapshot.items() if is_worker(r,'run_bc_trial.py') and any(
        value.startswith(str(ROOT/'outputs/campaigns/bc100-r3-all-strategies/jobs')+'/') for value in r.get('argv',[]))]
    def core_cost(p):
        cmd=snapshot[p]['cmd']
        if '/dsh/visual/' in cmd:return 5
        if '/dsh/' in cmd or '/hermes/visual/' in cmd:return 3
        return 2
    core_growth=sum(max(0,core_cost(p)-len(descendants(p,snapshot))) for p in core)
    core_growth+=max(0,CORE_WORKERS-len(core))*CORE_COST
    # Adopt old supplemental workers that predate the shared ledger.
    known={r['pid'] for r in reservations}
    reservations=list(reservations)
    for pid,r in snapshot.items():
        if pid not in known and is_worker(r,'rq3_trial.py'):
            reservations.append({'pid':pid,'identity':r['identity'],'owner':'rq3-adopted','job_id':'prior-controller','process_cost':4})
    growth=0;alive=[]
    for r in reservations:
        p=r['pid']
        if p in snapshot and snapshot[p]['identity']==r['identity']:
            alive.append(r);growth+=max(0,r['process_cost']-len(descendants(p,snapshot)))
    projected=len(snapshot)+core_growth+growth+cost+MARGIN
    return projected<=LIMIT,{'visible':len(snapshot),'core_reserved_growth':core_growth,
        'supplement_reserved_growth':growth,'requested_cost':cost,'margin':MARGIN,'projected':projected,'limit':LIMIT},alive

def memory_capacity(reservations):
    base=Path('/sys/fs/cgroup')
    try:
        limit=int((base/'memory.max').read_text());current=int((base/'memory.current').read_text())
        stats=dict(line.split() for line in (base/'memory.stat').read_text().splitlines())
        working=max(0,current-int(stats.get('inactive_file',0)))
    except (OSError,ValueError):return False,{'reason':'cgroup_memory_unavailable'}
    # File-backed cache is reclaimable. Reserve1GiB per supplemental worker,
    # plus8GiB for core growth; deliberately conservative, not an RSS forecast.
    projected=working+(len(reservations)+1)*1024**3+8*1024**3
    return projected<limit,{'working_set_bytes':working,'memory_limit_bytes':limit,'projected_bytes':projected}


def spawn_admitted(command,*,owner,job_id,log_path,cwd=ROOT,process_cost=4):
    if not isinstance(process_cost,int) or process_cost<1:raise ValueError('Positive process_cost required')
    STATE.mkdir(parents=True,exist_ok=True)
    with (STATE/'experiment-admission.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        ledger=STATE/'experiment-admission.json'
        previous=json.loads(ledger.read_text()).get('reservations',[]) if ledger.exists() else []
        ok,report,alive=capacity(processes(),previous,process_cost)
        controlled_reserved=sum(r['process_cost'] for r in alive if not r['owner'].startswith('rq3'))
        fair_reserve=max(0,8-controlled_reserved) if owner=='rq3' else 0
        report['controlled_validation_reserve']=fair_reserve
        report['projected']+=fair_reserve
        ok=report['projected']<=LIMIT
        memory_ok,memory=memory_capacity(alive)
        report['memory']=memory
        if not ok or not memory_ok:
            atomic(ledger,{'updated_unix':time.time(),'reservations':alive,'last_decision':dict(report,admitted=False,owner=owner,job_id=job_id)})
            return None,'process_capacity_reserved_for_core'
        Path(log_path).parent.mkdir(parents=True,exist_ok=True)
        with Path(log_path).open('a') as log:
            p=subprocess.Popen(command,cwd=cwd,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        alive.append({'pid':p.pid,'identity':process_identity(p.pid),'owner':owner,'job_id':job_id,'process_cost':process_cost})
        atomic(ledger,{'updated_unix':time.time(),'reservations':alive,'last_decision':dict(report,admitted=True,owner=owner,job_id=job_id)})
        return p,'admitted'
