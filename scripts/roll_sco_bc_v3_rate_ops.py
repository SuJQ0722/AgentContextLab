#!/usr/bin/env python3
"""One clean ops2 -> ops3 replacement per cell for recorded dispatch reduction.

Read-only cloud queries by default. --live creates only after ACP SUCCEEDED,
bound clean controller drain, namespace evidence, and proven new-name absence.
This tool never stops jobs, starts old jobs, or retries an unknown create.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import signal
import time
import resume_sco_bc_v3_after_reader_ops as resume
from replace_sco_bc_v3_after_reader_ops import create_argv, create_cli, error_reason

ROOT = resume.ROOT


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ops2_jobs(submissions):
    jobs=[]
    for harness,strategy in resume.CELLS:
        original='acl-bc-v3-'+harness+'-'+strategy.replace('_','-')
        name=original+'-ops2';directory=submissions/name
        request_path=directory/'request.json';response_path=directory/'response.json'
        request=resume.read(request_path);response=resume.read(response_path)
        required={'name':name,'generation':'ops2','operation':'create','harness':harness,'strategy':strategy}
        if any(request.get(k)!=v for k,v in required.items()) or response.get('state')!='submitted' or response.get('returncode')!=0:
            raise ValueError('Invalid independently submitted ops2 receipt: '+name)
        # Also validates the original workspace/allocation and exact name flags.
        create_argv(request,original+'-ops3')
        jobs.append({'name':name,'new_name':original+'-ops3','original_name':original,
                     'harness':harness,'strategy':strategy,'submission':request,
                     'parent_request':str(request_path),'parent_response':str(response_path),
                     'parent_request_sha256':sha(request_path),'parent_response_sha256':sha(response_path)})
    return jobs


def clean_controller(root,boot,exited):
    if exited.get('controller_exit_code')!=0:return None
    # A bootstrap signal is implemented as stop-dispatch + wait, never native kill.
    if exited.get('stopped') is True:return {'kind':'bootstrap_stop_and_drain'}
    # Main may signal only the controller. Its final durable state must prove drain.
    for path in (root/'controllers').glob('*/status.json'):
        status=resume.read(path)
        if (all(status.get(k)==boot.get(k) for k in ('hostname','boot_id','pid_namespace'))
                and status.get('pid')==boot.get('controller_pid') and status.get('start_identity')
                and status.get('stop_dispatch') is True and status.get('active_local')==0):
            return {'kind':'controller_stop_and_drain','status_path':str(path),'status_sha256':sha(path)}
    return None


def assess(root,plan,job,description):
    result={'name':job['new_name'],'replaces':job['name'],'eligible':False}
    if description.get('name')!=job['name'] or description.get('workspace_name')!='rl':
        return dict(result,reason='ACP identity mismatch')
    if description.get('state')!='SUCCEEDED':return dict(result,reason='Waiting for ACP SUCCEEDED',acp_state=description.get('state'))
    uid=description.get('uid','')
    if not re.fullmatch(r'[0-9a-f]{32}',uid):return dict(result,reason='ACP uid missing')
    host='pt-'+uid+'-worker-0';cell=job['harness']+'/'+job['strategy']
    candidates=[]
    for node in (root/'runtime/nodes').glob(host+'-*'):
        path=node/(job['harness']+'-'+job['strategy'])/'bootstrap.json'
        if path.exists():
            boot=resume.read(path)
            if boot.get('cell')==cell and boot.get('started_at_unix',0)>job['submission']['requested_at_unix']:
                candidates.append((boot['started_at_unix'],node,path,boot))
    if not candidates:return dict(result,reason='Missing bootstrap bound to submitted ops2')
    _,node,bootstrap_path,boot=max(candidates,key=lambda x:x[0])
    exit_path=bootstrap_path.parent/'exit.json';telemetry_path=node/'telemetry.json'
    if not exit_path.exists() or not telemetry_path.exists():return dict(result,reason='Missing durable exit or namespace telemetry')
    exited=resume.read(exit_path);telemetry=resume.read(telemetry_path)
    if (boot.get('hostname')!=host or not boot.get('boot_id') or not boot.get('pid_namespace')
            or node.name!=host+'-'+boot['boot_id']
            or any(telemetry.get(k)!=boot.get(k) for k in ('hostname','boot_id','pid_namespace'))):
        return dict(result,reason='Old namespace identity mismatch')
    if exited.get('finished_at_unix',0)<boot['started_at_unix']:return dict(result,reason='Exit predates bound bootstrap')
    drained=clean_controller(root,boot,exited)
    if not drained:return dict(result,reason='Controller clean drain not proven')
    pending=resume.pending_count(root,plan,job)
    return dict(result,eligible=pending>0,reason='Clean ops2 terminal; ready for fixed ops3 replacement' if pending else 'No untouched pending jobs',
                acp_state='SUCCEEDED',uid=uid,hostname=host,node_directory=str(node),
                retired_boot_id=boot['boot_id'],retired_pid_namespace=boot['pid_namespace'],pending=pending,
                bootstrap_exit=str(exit_path),bootstrap_exit_sha256=sha(exit_path),
                bootstrap_path=str(bootstrap_path),bootstrap_sha256=sha(bootstrap_path),clean_drain=drained)


def replacement_once(receipts,job,evidence,dispatch,dispatch_path,stopping=lambda:False,invoke=create_cli):
    if stopping():return {'state':'stopping_no_create'}
    name=job['new_name'];directory=receipts/name
    argv=create_argv(job['submission'],name)
    try:directory.mkdir(parents=True,exist_ok=False)
    except FileExistsError:return {'state':'existing_request_never_repeated'}
    sources=['scripts/roll_sco_bc_v3_rate_ops.py','scripts/bootstrap_bc_v3_node.py',
             'scripts/replace_sco_bc_v3_after_reader_ops.py','scripts/resume_sco_bc_v3_after_reader_ops.py']
    request={'name':name,'replaces':job['name'],'original_name':job['original_name'],'generation':'ops3',
             'harness':job['harness'],'strategy':job['strategy'],'operation':'create','argv':argv,
             'requested_at':resume.now(),'requested_at_unix':time.time(),'evidence':evidence,
             'parent_receipt':{k:job[k] for k in ('parent_request','parent_response','parent_request_sha256','parent_response_sha256')},
             'operational_dispatch':dispatch,'dispatch_config':str(dispatch_path),'dispatch_config_sha256':sha(dispatch_path),
             'source_sha256':{p:sha(ROOT/p) for p in sources},'worker_ceiling':32,
             'resources_image_mount_command_unchanged':True,'only_acp_argv_change':'--job-name and --name: ops2 to ops3',
             'claim_policy':'Original campaign pending-only; no retry of claimed or old attempts',
             'automatic_repeat_allowed':False}
    resume.atomic(directory/'request.json',request)
    retirement={'hostname':evidence['hostname'],'boot_id':evidence['retired_boot_id'],
                'pid_namespace':evidence['retired_pid_namespace'],'job_name':job['name'],
                'retired_at':resume.now(),'retired_at_unix':time.time(),
                'reason':'ACP SUCCEEDED and bound clean drain before ops3 dispatch reduction',
                'bootstrap_exit':evidence['bootstrap_exit'],'request_receipt':str(directory/'request.json')}
    retired_path=Path(evidence['node_directory'])/'retired.json'
    if retired_path.exists():
        old=resume.read(retired_path)
        if any(old.get(k)!=retirement[k] for k in ('hostname','boot_id','pid_namespace','job_name')):
            raise ValueError('Retirement identity conflicts; do not create')
    else:resume.atomic(retired_path,retirement)
    if stopping():response={'state':'not_sent_stopping','completed_at':resume.now()}
    elif sha(dispatch_path)!=request['dispatch_config_sha256'] or any(sha(ROOT/p)!=s for p,s in request['source_sha256'].items()):
        response={'state':'not_sent_source_changed','completed_at':resume.now()}
    else:
        outcome=invoke(argv)
        response={'state':'submitted' if outcome.get('returncode')==0 else 'unknown' if outcome.get('returncode') is None else 'rejected',
                  'completed_at':resume.now(),**outcome}
    resume.atomic(directory/'response.json',response)
    return {'state':response['state'],'receipt':str(directory)}


def cycle(args,stopping=lambda:False,query=resume.cli,create=create_cli):
    plan=resume.read(args.root/'plan.json');dispatch=resume.read(args.dispatch_config)
    if dispatch.get('active_workers_per_cloud_instance')!=4 or dispatch.get('local_target_workers')!=4:
        raise ValueError('Rate-ops3 requires approved cloud4/local4 dispatch')
    rows=[]
    for job in ops2_jobs(args.submissions):
        if stopping():break
        if job['harness'] not in args.harness or job['strategy'] not in args.strategy:continue
        name=job['new_name'];directory=args.receipts/name
        if directory.exists():
            response=resume.read(directory/'response.json') if (directory/'response.json').exists() else {'state':'unknown'}
            rows.append({'name':name,'state':response['state'],'automatic_repeat_allowed':False});continue
        try:
            outcome=query(args.sco,'describe',job['name'])
            if outcome.get('returncode')!=0:
                rows.append({'name':name,'eligible':False,'reason':'Old ACP query failed'});continue
            row=assess(args.root,plan,job,json.loads(outcome['stdout']))
            if row.get('eligible'):
                existing=query(args.sco,'describe',name)
                if existing.get('returncode')==0:row.update(eligible=False,reason='Ops3 name already exists; never recreate')
                elif existing.get('returncode') is None or not error_reason(existing,'trainingJobNotFound'):
                    row.update(eligible=False,reason='New-name absence not proven')
                elif args.live:row['create']=replacement_once(args.receipts,job,row,dispatch,args.dispatch_config,stopping,create)
            rows.append(row)
        except (OSError,ValueError,KeyError,TypeError) as error:
            rows.append({'name':name,'eligible':False,'reason':'Incomplete evidence; no automatic create retry','error_type':type(error).__name__})
    return {'timestamp':resume.now(),'mode':'live' if args.live else 'dry_run','jobs':rows,'model_probes':0,
            'generation':'ops3','dispatch':dispatch,'remote_signals_sent':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=resume.CAMPAIGN)
    parser.add_argument('--submissions',type=Path,default=ROOT/'outputs/cloud-runtime/replacement-submissions')
    parser.add_argument('--receipts',type=Path,default=ROOT/'outputs/cloud-runtime/rate-replacements')
    parser.add_argument('--dispatch-config',type=Path,default=ROOT/'configs/cloud-dispatch-ops-v2.json')
    parser.add_argument('--sco',type=Path,default=ROOT/'.tools/sco-tj/cli/sco')
    parser.add_argument('--harness',nargs='+',choices=['hermes','dsh'],default=['hermes','dsh'])
    parser.add_argument('--strategy',nargs='+',choices=['none','summarize','sliding_window','discard','visual'],default=['none','summarize','sliding_window','discard','visual'])
    parser.add_argument('--live',action='store_true');parser.add_argument('--watch',action='store_true')
    args=parser.parse_args();stopped=False
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopped:
        try:report=cycle(args,lambda:stopped)
        except (OSError,ValueError,KeyError,TypeError) as error:
            report={'timestamp':resume.now(),'state':'evidence_error_no_dispatch','error_type':type(error).__name__}
        resume.atomic(args.receipts/'status.json',report);print(json.dumps(report),flush=True)
        if not args.watch:break
        until=time.monotonic()+30
        while not stopped and time.monotonic()<until:time.sleep(.2)


if __name__=='__main__':main()
