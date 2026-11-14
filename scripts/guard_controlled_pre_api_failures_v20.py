"""Stop new controlled dispatch on first unexpected pre-model system failure."""
import fcntl
import json
from pathlib import Path
import time
from controlled_mmbc_source_v20 import DEFAULT, read, save, METHODS

ERRORS={'ValueError','KeyError','TypeError','ImportError','ModuleNotFoundError','FileNotFoundError','RuntimeError'}
OUT=DEFAULT/'runtime/pre-api-guard'


def first_bad(method,seen):
    for job in read(DEFAULT/'plan.json')['jobs']:
        if job['method']!=method or job['job_id'] in seen:continue
        out=Path(job['output_path']);terminal=out/'terminal.json'
        if not terminal.exists():continue
        t=read(terminal);seen.add(job['job_id'])
        if t.get('new_attempts')!=1 or t.get('status')!='failed':continue
        result=read(out/'result.json') if (out/'result.json').exists()else{}
        model_events=False
        for name in ('call-starts.jsonl','calls.jsonl','transport-phases-v3.jsonl'):
            p=out/'metrics'/name
            if not p.exists():continue
            for line in p.read_text().splitlines():
                try:r=json.loads(line)
                except ValueError:continue
                if name!='transport-phases-v3.jsonl' or r.get('event')=='request_started':model_events=True
        if model_events:continue
        if result.get('error_type') in ERRORS or not result:
            return {'job_id':job['job_id'],'terminal_path':str(terminal),'error_type':result.get('error_type','worker_failed_before_result'),
                    'model_events_observed':False,'new_dispatch_only':True,'current_native_workers_not_signaled':True}
    return None


def main():
    OUT.mkdir(parents=True,exist_ok=True);lock=(OUT/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    seen=set();stopped=set()
    while True:
        for method in METHODS:
            if method in stopped:continue
            bad=first_bad(method,seen)
            if bad:
                marker=DEFAULT/'cells'/method/'STOP';marker.parent.mkdir(parents=True,exist_ok=True)
                if not marker.exists():save(marker,{'at':time.time(),'reason':'Unexpected pre-API system failure; stop new dispatch for repair',**bad})
                save(OUT/(method+'-trigger.json'),{'at':time.time(),**bad});stopped.add(method)
        statuses=[read(DEFAULT/'cells'/m/'status.json') if(DEFAULT/'cells'/m/'status.json').exists()else{}for m in METHODS]
        save(OUT/'status.json',{'at':time.time(),'methods_stopped':sorted(stopped),'terminal_jobs_inspected':len(seen),'model_calls':0,'automatic_retry':False})
        if all(s.get('finished') and s.get('active')==0 for s in statuses):return
        time.sleep(2)

if __name__=='__main__':main()
