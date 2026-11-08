#!/usr/bin/env python3
"""One ops2 replacement per original cell after ACP explicitly rejects restart.

Dry-run by default. Original submissions and trial claims remain immutable.
Only pending work is resumed; unknown create outcomes are never resubmitted.
Visual launch is held unless separately released with --release-visual.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import subprocess
import time
import resume_sco_bc_v3_after_reader_ops as resume

ROOT = resume.ROOT


def error_reason(outcome, reason):
    text = outcome.get('stderr', '') + outcome.get('stdout', '')
    for _ in range(4): text = text.replace('\\"', '"')
    return bool(re.search(r'"reason"\s*:\s*"' + re.escape(reason) + r'"', text))


def create_argv(submission, name):
    argv = list(submission['argv'])
    if argv[1:4] != ['acp', 'jobs', 'create']: raise ValueError('Original command not ACP create')
    def argument(flag): return argv[argv.index(flag)+1]
    if argument('--workspace-name') != 'rl' or argument('--worker-nodes') != '1':
        raise ValueError('Unexpected workspace or allocation')
    if argument('--worker-spec') != 'N4lS.Iu.I80.8c32g': raise ValueError('Unexpected original worker spec')
    for flag in ('--job-name', '--name'):
        index = argv.index(flag)+1
        if argv[index] != submission['name']: raise ValueError('Original command name mismatch')
        argv[index] = name
    return argv


def create_cli(argv):
    try:
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120)
        return {'returncode':result.returncode,'stdout':resume.redact(result.stdout),'stderr':resume.redact(result.stderr)}
    except subprocess.TimeoutExpired: return {'returncode':None,'error_type':'TimeoutExpired'}
    except OSError as exc: return {'returncode':None,'error_type':type(exc).__name__,'errno':exc.errno}


def replacement_once(receipts, job, submission, evidence, dispatch, stopping=lambda:False, invoke=create_cli):
    name=job['name']+'-ops2'; directory=receipts/name
    if stopping(): return {'state':'stopping_no_create'}
    argv=create_argv(submission,name)
    try: directory.mkdir(parents=True,exist_ok=False)
    except FileExistsError: return {'state':'existing_request_never_repeated'}
    request={'name':name,'replaces':job['name'],'generation':'ops2','harness':job['harness'],
             'strategy':job['strategy'],'operation':'create','requested_at':resume.now(),'requested_at_unix':time.time(),
             'argv':argv,'evidence':evidence,'operational_dispatch':dispatch,'worker_ceiling':32,
             'model_and_strategy_unchanged':True,'claim_policy':'Existing campaign pending-only; never retry claimed jobs',
             'automatic_repeat_allowed':False,'bootstrap_sha256':hashlib.sha256((ROOT/'scripts/bootstrap_bc_v3_node.py').read_bytes()).hexdigest()}
    resume.atomic(directory/'request.json',request)
    if stopping(): response={'state':'not_sent_stopping','completed_at':resume.now()}
    else:
        outcome=invoke(argv)
        response={'state':'submitted' if outcome.get('returncode') == 0 else 'unknown' if outcome.get('returncode') is None else 'rejected',
                  'completed_at':resume.now(),**outcome}
    resume.atomic(directory/'response.json',response)
    return {'state':response['state'],'receipt':str(directory)}


def assess_replacement(root,plan,job,submissions,resume_receipts,sco,query=resume.cli):
    name=job['name']; directory=resume_receipts/name
    response_path=directory/'response.json';request_path=directory/'request.json'
    result={'name':name+'-ops2','replaces':name,'eligible':False}
    if not response_path.exists() or not request_path.exists(): return dict(result,reason='Original restart response missing')
    response=resume.read(response_path);request=resume.read(request_path)
    if not (response.get('state')=='rejected' and response.get('returncode') not in (None,0)
            and error_reason(response,'tjUpdateNotSupportStart') and request.get('job',{}).get('name')==name
            and request.get('evidence',{}).get('acp_state')=='SUCCEEDED'):
        return dict(result,reason='No explicit unsupported-start rejection for succeeded original job')
    described=query(sco,'describe',name)
    if described.get('returncode') != 0:return dict(result,reason='Original describe failed')
    description=json.loads(described['stdout'])
    if description.get('state')!='SUCCEEDED':return dict(result,reason='Original is not SUCCEEDED; no replacement')
    evidence=resume.assess(root,plan,job,description)
    if not evidence.get('eligible'):return dict(result,reason=evidence['reason'])
    existing=query(sco,'describe',name+'-ops2')
    if existing.get('returncode') == 0:return dict(result,reason='Replacement already exists; never create another')
    if existing.get('returncode') is None or not error_reason(existing,'trainingJobNotFound'):
        return dict(result,reason='Replacement absence not proven')
    result.update(eligible=True,reason='Original clean terminal; unsupported restart; fixed replacement absent',
                  original_evidence=evidence,original_start_request=str(request_path),original_start_response=str(response_path),
                  original_rejection_sha256=hashlib.sha256(response_path.read_bytes()).hexdigest())
    return result


def cycle(args,stopping=lambda:False,query=resume.cli,create=create_cli):
    plan=resume.read(args.root/'plan.json');dispatch=resume.read(ROOT/'configs/cloud-dispatch-ops-v1.json')
    if dispatch.get('active_workers_per_cloud_instance')!=8:
        raise ValueError('This authorized replacement launch requires protective concurrency 8 (ceiling32)')
    rows=[]
    for job in resume.original_jobs(args.submissions):
        if job['harness'] not in args.harness or job['strategy'] not in args.strategy:continue
        if stopping():break
        name=job['name']+'-ops2';directory=args.receipts/name
        try:
            if directory.exists():
                response=resume.read(directory/'response.json') if (directory/'response.json').exists() else {'state':'unknown'}
                row={'name':name,'state':response['state'],'automatic_repeat_allowed':False}
                if response['state']=='submitted':
                    current=query(args.sco,'describe',name)
                    if current.get('returncode')==0:
                        newjob=dict(job,name=name)
                        row['post_start']=resume.post_start(args.root,newjob,resume.read(directory/'request.json'),json.loads(current['stdout']))
                rows.append(row);continue
            row=assess_replacement(args.root,plan,job,args.submissions,args.resume_receipts,args.sco,query)
            if job['strategy']=='visual' and not args.release_visual:
                row.update(eligible=False,reason='Visual launch held pending separate release')
            if row.get('eligible') and args.live:
                row['create']=replacement_once(args.receipts,job,resume.read(args.submissions/(job['name']+'.json')),
                                                row,dispatch,stopping,create)
            rows.append(row)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            rows.append({'name':name,'eligible':False,'reason':'Invalid or incomplete evidence','error_type':type(exc).__name__})
    return {'timestamp':resume.now(),'mode':'live' if args.live else 'dry_run','jobs':rows,'model_probes':0,
            'registry_note':'Replacement receipts are separate; global monitors must exclude replaced original generations, not count both.'}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=resume.CAMPAIGN)
    ap.add_argument('--submissions',type=Path,default=ROOT/'outputs/cloud-runtime/submissions')
    ap.add_argument('--resume-receipts',type=Path,default=ROOT/'outputs/cloud-runtime/reader-resume')
    ap.add_argument('--receipts',type=Path,default=ROOT/'outputs/cloud-runtime/replacement-submissions')
    ap.add_argument('--sco',type=Path,default=ROOT/'.tools/sco-tj/cli/sco')
    ap.add_argument('--harness',nargs='+',choices=['hermes','dsh'],default=['hermes','dsh'])
    ap.add_argument('--strategy',nargs='+',choices=['none','summarize','sliding_window','discard','visual'],default=['none','summarize','sliding_window','discard','visual'])
    ap.add_argument('--release-visual',action='store_true');ap.add_argument('--live',action='store_true');ap.add_argument('--watch',action='store_true')
    args=ap.parse_args();stopped=False
    def stop(*_):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopped:
        try:report=cycle(args,lambda:stopped)
        except (OSError,ValueError,TypeError,KeyError) as exc:
            report={'timestamp':resume.now(),'state':'evidence_error_no_dispatch','error_type':type(exc).__name__}
        resume.atomic(args.receipts/'status.json',report);print(json.dumps(report),flush=True)
        if not args.watch:break
        deadline=time.monotonic()+30
        while not stopped and time.monotonic()<deadline:time.sleep(.2)


if __name__=='__main__':main()
