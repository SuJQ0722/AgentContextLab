"""AFS/proxy runtime repair for a fresh inline information-loss generation.

Old generations are read-only. Only exact successful request fingerprints and
completed identical conditions may be reused; failure artifacts are preserved.
"""
import argparse
import concurrent.futures
import copy
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import re
import time
import info_loss_inline_retry_v8 as previous
from lab import ROOT

VERSION='info-loss-inline-runtime-v9'
PROXY='http://10.120.0.246:7890'
DEFAULT=ROOT/'outputs/experiment6/inline-runtime-v9'
_REAL_FLOCK=fcntl.flock


def blocking_flock(operation, fd, flags, *, timeout_seconds=3600, now=time.monotonic, sleep=time.sleep):
    """AFS may report EAGAIN even for blocking locks; never relax LOCK_NB."""
    if flags & fcntl.LOCK_NB or not flags & (fcntl.LOCK_EX|fcntl.LOCK_SH):
        return operation(fd,flags)
    if not math.isfinite(timeout_seconds) or timeout_seconds<=0:
        raise ValueError('Positive lock deadline required')
    deadline=now()+timeout_seconds;delay=.1
    while True:
        try:return operation(fd,flags)
        except OSError as exc:
            if exc.errno!=errno.EAGAIN:raise
            remaining=deadline-now()
            if remaining<=0:raise previous.Deadline() from None
            # Python sleep is interrupted by the existing per-condition SIGALRM.
            sleep(min(delay,remaining));delay=min(1.,delay*2)


def configure_proxy(env):
    for key in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):env[key]=PROXY
    for key in ('ALL_PROXY','all_proxy'):env.pop(key,None)
    return env


def install_runtime():
    configure_proxy(os.environ)
    if not getattr(fcntl.flock,'_acl_info_loss_v9',False):
        def flock(fd,flags):return blocking_flock(_REAL_FLOCK,fd,flags)
        flock._acl_info_loss_v9=True;fcntl.flock=flock


def scientific_case(case):
    value=copy.deepcopy(case)
    for representation in value.get('tiled_representations',{}).values():
        for item in representation.get('images',[]):item.pop('path',None)
    return value


def reuse_successes(old,out,old_manifest,new_manifest):
    old_cases={c['id']:scientific_case(c) for c in old_manifest['cases']}
    for case in new_manifest['cases']:
        if old_cases.get(case['id'])!=scientific_case(case):raise ValueError('Old and new case evidence differ')
    reused=[]
    for start in sorted(old.glob('conditions/*/*/attempts/*/calls/*/started.json')):
        response=start.parent/'response.json'
        if not response.exists():continue
        started=previous.phase.read(start);value=previous.phase.read(response)
        fingerprint=started.get('request_fingerprint','')
        if value.get('status')!='completed' or not re.fullmatch('[a-f0-9]{64}',fingerprint):continue
        target=out/'completed-calls'/fingerprint
        if target.exists():continue
        previous.save(target,{**value,'reused_source':str(response),'new_request':False})
        reused.append({'kind':'exact_successful_request','request_fingerprint':fingerprint,
                       'source':str(response),'source_sha256':previous.phase.sha(response),
                       'request_proof':str(start),'request_proof_sha256':previous.phase.sha(start),
                       'target':str(target),'target_sha256':previous.phase.sha(target)})
    # Completed condition results are already scientifically complete; retain
    # those irrespective of their score. Failed/blocked/timeouts are not copied.
    for result in sorted(old.glob('conditions/*/*/result.json')):
        value=previous.phase.read(result)
        if value.get('status')!='completed':continue
        case=result.parent.parent.name;method=result.parent.name
        if case not in old_cases or method not in new_manifest['methods']:raise ValueError('Unknown completed condition')
        target=out/result.relative_to(old)
        previous.save(target,{**value,'reused_source_result':str(result),'new_model_calls':0})
        reused.append({'kind':'completed_condition','source':str(result),'source_sha256':previous.phase.sha(result),
                       'target':str(target),'target_sha256':previous.phase.sha(target)})
    return reused


def prepare(out,old,stop_proof):
    out,old,stop_proof=map(lambda p:Path(p).resolve(),(out,old,stop_proof))
    if out==old or out.is_relative_to(old) or old.is_relative_to(out):raise ValueError('Independent output generation required')
    proof=previous.phase.read(stop_proof)
    if proof.get('state')!='SUSPENDED' or proof.get('ready_replicas')!=0 or not proof.get('uid'):
        raise ValueError('Old CCI must be confirmed SUSPENDED with zero replicas')
    prior=previous.phase.read(old/'manifest.json');previous.verify(old,prior)
    if prior.get('version')!=previous.VERSION:raise ValueError('Expected original inline V8 generation')
    # All source bytes and scientific prompts come from the original phase4.
    manifest=previous.prepare(out,Path(prior['parent_manifest']).parent)
    reused=reuse_successes(old,out,prior,manifest)
    manifest.update(version=VERSION,previous_generation=str(old),previous_manifest_sha256=previous.phase.sha(old/'manifest.json'),
                    old_stop_proof=str(stop_proof),old_stop_proof_sha256=previous.phase.sha(stop_proof),
                    runtime_repair={'explicit_proxy':PROXY,'blocking_flock_eagain_retry':True,'nonblocking_locks_unchanged':True},
                    reused_successes=reused)
    manifest['implementation_sha256']['scripts/info_loss_inline_runtime_v9.py']=previous.phase.sha(__file__)
    previous.save(out/'manifest.json',manifest);(out/'manifest.sha256').write_text(previous.phase.sha(out/'manifest.json')+'\n')
    return manifest


def verify(out,manifest):
    if manifest.get('version')!=VERSION or previous.phase.sha(out/'manifest.json')!=(out/'manifest.sha256').read_text().strip():raise ValueError('V9 manifest changed')
    for name,digest in manifest['implementation_sha256'].items():
        if previous.phase.sha(ROOT/name)!=digest:raise ValueError('Frozen implementation changed')
    for path,digest in [(manifest['parent_manifest'],manifest['parent_manifest_sha256']),
                        (str(Path(manifest['previous_generation'])/'manifest.json'),manifest['previous_manifest_sha256']),
                        (manifest['old_stop_proof'],manifest['old_stop_proof_sha256'])]:
        if previous.phase.sha(path)!=digest:raise ValueError('Frozen generation provenance changed')
    for item in manifest['reused_successes']:
        for path_key,hash_key in [('source','source_sha256'),('target','target_sha256'),('request_proof','request_proof_sha256')]:
            if path_key in item and previous.phase.sha(item[path_key])!=item[hash_key]:raise ValueError('Reused success proof changed')


def condition(args):
    install_runtime();return previous.run_condition(args)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=DEFAULT)
    parser.add_argument('--previous',type=Path,default=previous.DEFAULT)
    parser.add_argument('--stop-proof',type=Path)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--resume',action='store_true');parser.add_argument('--live',action='store_true')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=True)
    install_runtime()
    with (out/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.prepare:
            if not args.stop_proof:parser.error('--prepare requires --stop-proof')
            manifest=prepare(out,args.previous,args.stop_proof)
        else:manifest=previous.phase.read(out/'manifest.json')
        verify(out,manifest)
        if not args.live:
            print(json.dumps({'paid_calls':0,'version':VERSION,'cases':len(manifest['cases']),'conditions':len(manifest['cases'])*len(manifest['methods']),
                              'concurrency':16,'explicit_proxy':PROXY,'reused_successes':len(manifest['reused_successes'])}));return
        if not args.resume:parser.error('--live requires --resume')
        rows=[]
        with concurrent.futures.ProcessPoolExecutor(max_workers=16,initializer=install_runtime) as pool:
            futures=[pool.submit(condition,(str(out),case['id'],method)) for case in manifest['cases'] for method in manifest['methods']]
            for future in concurrent.futures.as_completed(futures):
                result=future.result();rows.append(result);previous.save(out/'condition-results.json',rows)
                responses=list(out.glob('conditions/*/*/attempts/*/calls/*/response.json'));starts=list(out.glob('conditions/*/*/attempts/*/calls/*/started.json'))
                usage=previous.summarize_usage([previous.phase.read(p) for p in responses],len(starts))
                usage.update(scope='V9 new attempts only; historical reused calls remain in previous generation',previous_generation=str(args.previous))
                previous.save(out/'usage-summary.json',usage)
                previous.save(out/'live-status.json',{'at':time.time(),'version':VERSION,'conditions_finished':len(rows),'conditions_total':len(futures),
                    'statuses':{status:sum(r['status']==status for r in rows) for status in ('completed','timeout','blocked','failed')},'calls_started':len(starts),'calls_returned':len(responses)})


if __name__=='__main__':main()
