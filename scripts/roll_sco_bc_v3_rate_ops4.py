#!/usr/bin/env python3
"""One clean ops3 -> ops4 replacement per cell; default cloud queries only.

Only --live permits create. No stop/start operations, model calls, or automatic
retry of any existing create receipt. Parent cells not submitted yet are awaited.
"""
import argparse
import json
from pathlib import Path
import signal
import time
import roll_sco_bc_v3_rate_ops as parent
from replace_sco_bc_v3_after_reader_ops import create_argv,create_cli,error_reason

resume=parent.resume
ROOT=parent.ROOT
sha=parent.sha
LEGACY_VISUAL_RECEIPTS=ROOT/'outputs/cloud-runtime/visual-rate-replacements'


def parent_job(submissions,harness,strategy):
    original='acl-bc-v3-'+harness+'-'+strategy.replace('_','-')
    name=original+'-ops3';new_name=original+'-ops4';directory=submissions/name
    request_path=directory/'request.json';response_path=directory/'response.json'
    if not request_path.exists() or not response_path.exists():return None
    request=resume.read(request_path);response=resume.read(response_path)
    required={'name':name,'generation':'ops3','operation':'create','harness':harness,'strategy':strategy}
    if any(request.get(k)!=v for k,v in required.items()):raise ValueError('Parent ops3 identity mismatch')
    if response.get('state')!='submitted' or response.get('returncode')!=0:return None
    create_argv(request,new_name)
    return {'name':name,'new_name':new_name,'original_name':original,
            'harness':harness,'strategy':strategy,'submission':request,
            'parent_request':str(request_path),'parent_response':str(response_path),
            'parent_request_sha256':sha(request_path),'parent_response_sha256':sha(response_path)}


def replacement_once(receipts,job,evidence,dispatch,dispatch_path,stopping=lambda:False,invoke=create_cli):
    if stopping():return {'state':'stopping_no_create'}
    name=job['new_name'];directory=receipts/name
    argv=create_argv(job['submission'],name)
    try:directory.mkdir(parents=True,exist_ok=False)
    except FileExistsError:return {'state':'existing_request_never_repeated'}
    sources=['scripts/roll_sco_bc_v3_rate_ops4.py','scripts/roll_sco_bc_v3_rate_ops.py','scripts/bootstrap_bc_v3_node.py',
             'scripts/replace_sco_bc_v3_after_reader_ops.py','scripts/resume_sco_bc_v3_after_reader_ops.py']
    request={'name':name,'replaces':job['name'],'original_name':job['original_name'],'generation':'ops4',
             'harness':job['harness'],'strategy':job['strategy'],'operation':'create','argv':argv,
             'requested_at':resume.now(),'requested_at_unix':time.time(),'evidence':evidence,
             'parent_receipt':{k:job[k] for k in ('parent_request','parent_response','parent_request_sha256','parent_response_sha256')},
             'operational_dispatch':dispatch,'dispatch_config':str(dispatch_path),'dispatch_config_sha256':sha(dispatch_path),
             'source_sha256':{p:sha(ROOT/p) for p in sources},'worker_ceiling':32,'active_workers_this_cell':1,
             'resources_image_mount_command_unchanged':True,'only_acp_argv_change':'--job-name and --name: ops3 to ops4',
             'claim_policy':'Original campaign pending-only; no retry of claimed or old attempts',
             'automatic_repeat_allowed':False}
    resume.atomic(directory/'request.json',request)
    retirement={'hostname':evidence['hostname'],'boot_id':evidence['retired_boot_id'],
                'pid_namespace':evidence['retired_pid_namespace'],'job_name':job['name'],
                'retired_at':resume.now(),'retired_at_unix':time.time(),
                'reason':'ACP SUCCEEDED and bound clean drain before ops4 dispatch reduction',
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
    if dispatch.get('active_workers_per_cloud_instance')!=1 or dispatch.get('local_target_workers')!=2:
        raise ValueError('Ops4 requires approved cloud1/local2 dispatch')
    rows=[]
    for harness,strategy in resume.CELLS:
        if stopping():break
        if harness not in args.harness or strategy not in args.strategy:continue
        name='acl-bc-v3-'+harness+'-'+strategy.replace('_','-')+'-ops4'
        directory=args.receipts/name
        try:
            if directory.exists():
                response=resume.read(directory/'response.json') if (directory/'response.json').exists() else {'state':'unknown'}
                rows.append({'name':name,'state':response['state'],'automatic_repeat_allowed':False});continue
            if (LEGACY_VISUAL_RECEIPTS/name).exists():
                rows.append({'name':name,'state':'existing_other_receipt_never_repeated',
                             'receipt':str(LEGACY_VISUAL_RECEIPTS/name),'automatic_repeat_allowed':False});continue
            job=parent_job(args.submissions,harness,strategy)
            if job is None:
                rows.append({'name':name,'eligible':False,'state':'awaiting_parent_submitted','reason':'Ops3 parent not independently confirmed submitted'});continue
            parent_workers=job['submission'].get('active_workers_this_cell',job['submission'].get('operational_dispatch',{}).get('active_workers_per_cloud_instance'))
            if parent_workers==1:
                rows.append({'name':name,'replaces':job['name'],'eligible':False,'state':'already_target_no_roll',
                             'reason':'Confirmed submitted ops3 request already selects one worker; no further replacement',
                             'parent_request':job['parent_request'],'parent_request_sha256':job['parent_request_sha256']});continue
            outcome=query(args.sco,'describe',job['name'])
            if outcome.get('returncode')!=0:
                rows.append({'name':name,'eligible':False,'reason':'Old ACP query failed'});continue
            row=parent.assess(args.root,plan,job,json.loads(outcome['stdout']))
            # The helper's identity/drain checks are generic; fix its historical labels.
            row['reason']=row.get('reason','').replace('ops3','ops4').replace('ops2','ops3')
            if row.get('eligible'):
                existing=query(args.sco,'describe',name)
                if existing.get('returncode')==0:row.update(eligible=False,reason='Ops4 name already exists; never recreate')
                elif existing.get('returncode') is None or not error_reason(existing,'trainingJobNotFound'):
                    row.update(eligible=False,reason='New-name absence not proven')
                elif args.live:row['create']=replacement_once(args.receipts,job,row,dispatch,args.dispatch_config,stopping,create)
            rows.append(row)
        except (OSError,ValueError,KeyError,TypeError) as error:
            rows.append({'name':name,'eligible':False,'reason':'Incomplete evidence; no automatic create retry','error_type':type(error).__name__})
    return {'timestamp':resume.now(),'mode':'live' if args.live else 'dry_run','jobs':rows,'model_probes':0,
            'generation':'ops4','dispatch':dispatch,'remote_signals_sent':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=resume.CAMPAIGN)
    parser.add_argument('--submissions',type=Path,default=ROOT/'outputs/cloud-runtime/rate-replacements')
    parser.add_argument('--receipts',type=Path,default=ROOT/'outputs/cloud-runtime/final-rate-replacements')
    parser.add_argument('--dispatch-config',type=Path,default=ROOT/'configs/cloud-dispatch-ops-v3.json')
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

