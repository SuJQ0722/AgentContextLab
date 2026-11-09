"""Explicit one-retry selection for controlled v4; never overwrite initial attempts."""
import hashlib,json,os
from pathlib import Path
from run_bc_trial import atomic,process_identity
from experiment_admission_v4 import processes
VERSION='controlled-v4-explicit-network-retry-ops2'
LEDGER='attempt-selection-ops2.json'
AUTHORIZED_JOB='browsecomp_v3/q_001_r01/summary'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def selection(root):
    root=Path(root).resolve();path=root/LEDGER
    if not path.exists():return {}
    value=read(path)
    if value['version']!=VERSION or value['plan_sha256']!=sha(root/'plan.json') or value['config_sha256']!=sha(root/'experiment.json'):raise ValueError('Retry parent lineage mismatch')
    for job,entry in value['entries'].items():
        if job!=AUTHORIZED_JOB:raise ValueError('Retry not in explicit authorization')
        original=root/'jobs'/job;chosen=original/'attempt_002'
        if entry['selected_out']!=str(chosen) or entry['original_out']!=str(original):raise ValueError('Retry output path mismatch')
        for key,path in [('original_result_sha256',original/'result.json'),('original_spec_sha256',original/'spec.json'),('selected_spec_sha256',chosen/'spec.json')]:
            if entry[key]!=sha(path):raise ValueError('Retry source/spec changed')
        spec=read(chosen/'spec.json')
        if entry['prefix_sha256']!=sha(spec['prefix_path']):raise ValueError('Retry prefix changed')
        if read(original/'spec.json')!=spec:raise ValueError('Retry changed scientific spec')
    return value['entries']
def selected_out(root,job_id):
    root=Path(root).resolve();entry=selection(root).get(job_id)
    return Path(entry['selected_out']) if entry else root/'jobs'/job_id

def prepare_retry(root):
    root=Path(root).resolve()
    if (root/LEDGER).exists():return selection(root)
    plan=read(root/'plan.json')
    if AUTHORIZED_JOB not in {j['job_id'] for j in plan['jobs']}:raise ValueError('Authorized job absent from fixed cohort')
    original=root/'jobs'/AUTHORIZED_JOB;result=read(original/'result.json');spec=read(original/'spec.json')
    if result.get('status')!='failed' or result.get('error_type')!='APIConnectionError':raise ValueError('Only the identified network-failed attempt is authorized')
    if spec['model']!='deepseek-v4.1-flash-1017/zijian/sfb':raise ValueError('Unexpected retry model')
    owner=read(original/'supervisor.json');snapshot=processes()
    if owner['pid'] in snapshot and snapshot[owner['pid']]['identity']==owner['identity']:raise ValueError('Original supervisor still exists')
    for pid,row in snapshot.items():
        argv=row.get('argv',[])
        if '--out' in argv:
            try:target=Path(argv[argv.index('--out')+1]).resolve()
            except (ValueError,IndexError):continue
            if target==original:raise ValueError('Original native worker still exists')
    started=read(original/'worker-started.json')
    if started['pid'] in snapshot:raise ValueError('Original worker PID remains visible; verify identity before recovery')
    chosen=original/'attempt_002';chosen.mkdir(parents=True,exist_ok=True)
    if any((chosen/n).exists() for n in ('dispatch.json','worker-started.json','result.json')):raise ValueError('Retry already claimed without approved selection ledger')
    if (chosen/'spec.json').exists() and read(chosen/'spec.json')!=spec:raise ValueError('Existing retry spec differs')
    atomic(chosen/'spec.json',spec)
    entry={'original_out':str(original),'selected_out':str(chosen),'original_result_sha256':sha(original/'result.json'),
        'original_spec_sha256':sha(original/'spec.json'),'selected_spec_sha256':sha(chosen/'spec.json'),
        'prefix_sha256':sha(spec['prefix_path']),'original_supervisor':owner,'original_worker_pid':started['pid'],
        'original_processes_confirmed_absent':True,'reason':'Explicitly authorized one retry after APIConnectionError before first actual continuation',
        'selection_rule':'Always use attempt_002 regardless of grade or outcome; never choose the better result',
        'additional_attempt_limit':1,'both_attempt_costs_retained':True}
    value={'version':VERSION,'plan_sha256':sha(root/'plan.json'),'config_sha256':sha(root/'experiment.json'),'entries':{AUTHORIZED_JOB:entry}}
    with (root/LEDGER).open('x') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    return selection(root)
