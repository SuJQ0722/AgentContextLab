#!/usr/bin/env python3
"""io3 startup repair, after proven clean drain or verified FAILED namespace termination.

Only --live permits create. No stop/start operations, model calls, or automatic
retry of any existing create receipt. Parent cells not submitted yet are awaited.
"""
import argparse
import json
from pathlib import Path
import signal
import re
import time
import roll_sco_bc_v3_rate_ops as parent
from replace_sco_bc_v3_after_reader_ops import create_argv as parent_create_argv,create_cli,error_reason
from bc_route_runtime_v2 import RoutePlan, implementation_hashes
from bc_claim_publication_io3 import operational_record, validate_recovery

resume=parent.resume
ROOT=parent.ROOT
sha=parent.sha
LEGACY_VISUAL_RECEIPTS=ROOT/'outputs/cloud-runtime/visual-rate-replacements'


def create_argv(submission,name):
    original=submission['argv']
    for flag in ('--job-name','--name','--command','--workspace-name','--worker-nodes','--worker-spec'):
        if original.count(flag)!=1:raise ValueError('Ambiguous original create argument')
    old_prefix,old_generation=submission['name'].rsplit('-',1)
    if (old_generation,name) not in (('ops4',old_prefix+'-ops5'),('ops5',old_prefix+'-ops6')):
        raise ValueError('Successor must preserve exact cell name and advance one approved generation')
    argv=parent_create_argv(submission,name)
    index=argv.index('--command')+1
    allowed=[str(ROOT/'scripts/bootstrap_bc_v3_node.py'),str(ROOT/'scripts/bootstrap_bc_v3_node_routes1.py'),str(ROOT/'scripts/bootstrap_bc_v3_node_routes2.py')]
    matches=[value for value in allowed if argv[index].count(value)==1]
    if len(matches)!=1:raise ValueError('Unexpected parent bootstrap command')
    argv[index]=argv[index].replace(matches[0],str(ROOT/'scripts/bootstrap_bc_v3_node_routes2_io3.py'))
    return argv


def parent_job(submissions,harness,strategy,parent_generation,new_generation):
    original='acl-bc-v3-'+harness+'-'+strategy.replace('_','-')
    name=original+'-'+parent_generation;new_name=original+'-'+new_generation;directory=submissions/name
    request_path=directory/'request.json';response_path=directory/'response.json'
    if not request_path.exists() or not response_path.exists():return None
    request=resume.read(request_path);response=resume.read(response_path)
    required={'name':name,'generation':parent_generation,'operation':'create','harness':harness,'strategy':strategy}
    if any(request.get(k)!=v for k,v in required.items()):raise ValueError('Parent generation identity mismatch')
    if response.get('state')!='submitted' or response.get('returncode')!=0:return None
    create_argv(request,new_name)
    return {'name':name,'new_name':new_name,'original_name':original,
            'harness':harness,'strategy':strategy,'submission':request,
            'parent_request':str(request_path),'parent_response':str(response_path),
            'parent_request_sha256':sha(request_path),'parent_response_sha256':sha(response_path)}


def assess_failed(root,plan,job,description):
    result={'name':job['new_name'],'replaces':job['name'],'eligible':False}
    proof_path=ROOT/'outputs/cloud-runtime/io3-recovery'/(job['harness']+'-'+job['strategy'])/'terminated-namespace.json'
    proof=resume.read(proof_path)
    if not isinstance(description.get('uid'),str) or not re.fullmatch(r'[0-9a-f]{32}',description['uid']):
        raise ValueError('Official ACP namespace uid missing')
    if (description.get('name')!=job['name'] or description.get('workspace_name')!='rl'
            or description.get('state')!='FAILED' or proof.get('name')!=job['name']
            or proof.get('schema')!='acp-terminated-namespace-v1' or proof.get('platform_state')!='FAILED'
            or proof.get('namespace_terminated') is not True):raise ValueError('Failed namespace identity not established')
    artifacts={}
    for key in ('describe','bootstrap','exit','inventory'):
        p=Path(proof[key+'_path'])
        if not p.is_absolute():raise ValueError('Failed namespace artifact paths must be absolute')
        if sha(p)!=proof[key+'_sha256']:raise ValueError('Failed namespace artifact changed')
        artifacts[key]=resume.read(p)
    old=artifacts['describe'];boot=artifacts['bootstrap'];exited=artifacts['exit']
    if (old.get('uid')!=description.get('uid') or old.get('name')!=job['name']
            or old.get('state')!='FAILED' or old.get('workspace_name')!='rl'
            or proof.get('uid')!=description.get('uid')
            or proof.get('hostname')!='pt-'+description['uid']+'-worker-0'
            or any(boot.get(k)!=proof.get(k) or not proof.get(k) for k in ('hostname','boot_id','pid_namespace'))
            or exited.get('controller_exit_code')!=1
            or exited.get('finished_at_unix',0)<boot.get('started_at_unix',0)
            or proof.get('observed_at_unix',0)<exited.get('finished_at_unix',0)):
        raise ValueError('Failed namespace termination proof mismatch')
    cell=job['harness']+'/'+job['strategy'];cell_directory=job['harness']+'-'+job['strategy']
    bootstrap_path=Path(proof['bootstrap_path']).resolve();exit_path=Path(proof['exit_path']).resolve()
    if (bootstrap_path.name!='bootstrap.json' or exit_path.name!='exit.json'
            or exit_path.parent!=bootstrap_path.parent or bootstrap_path.parent.name!=cell_directory
            or boot.get('cell')!=cell
            or boot.get('started_at_unix',0)<=job['submission'].get('requested_at_unix',float('inf'))):
        raise ValueError('Failed bootstrap/exit do not bind the submitted cell')
    node=bootstrap_path.parent.parent
    if node.parent!=root/'runtime/nodes' or node.name!=proof['hostname']+'-'+proof['boot_id']:
        raise ValueError('Failed namespace node directory mismatch')
    inventory=artifacts['inventory']
    if inventory.get('cell')!=cell or not isinstance(inventory.get('claims'),list):
        raise ValueError('Recovery inventory belongs to another cell')
    candidate_ids=set();seen=set();planned_ids={j['job_id'] for j in plan['jobs'] if j.get('harness')==job['harness'] and j.get('strategy')==job['strategy']}
    for item in inventory['claims']:
        jid=item.get('job_id')
        if not isinstance(jid,str) or not jid.startswith(cell+'/') or jid in seen or jid not in planned_ids:
            raise ValueError('Recovery inventory has duplicate or other-cell job')
        seen.add(jid)
        owner=resume.read(root/'jobs'/jid/'claim/owner.json')
        if owner.get('job_id')!=jid or any(owner.get(k)!=proof[k] for k in ('hostname','boot_id','pid_namespace')):
            raise ValueError('Recovery inventory owner differs from terminated namespace')
        if item.get('candidate_unstarted') is True and not item.get('forbidden_present'):
            candidate_ids.add(jid)
    manifest=proof_path.parent/'recovery-manifest.json'
    if not manifest.exists():raise ValueError('Reviewed explicit recovery manifest required before failed-cell replacement')
    document=resume.read(manifest)
    if (document.get('version')!='bc-v3-unstarted-recovery-manifest-io3'
            or Path(document.get('campaign_root','/missing')).resolve()!=root.resolve()
            or document.get('plan_sha256')!=sha(root/'plan.json')
            or document.get('route_plan_sha256')!=sha(root/'route-plan-v2.json')
            or not isinstance(document.get('entries'),list)):
        raise ValueError('Recovery manifest identity mismatch')
    recovered=set()
    for entry in document['entries']:
        jid=entry.get('job_id')
        if jid not in candidate_ids or jid in recovered:raise ValueError('Recovery entry not a unique unstarted inventory candidate')
        recovered.add(jid)
        spec_path=Path(entry['spec_path']);out=Path(entry['attempt_path']);auth=Path(entry['authorization_path'])
        if (not spec_path.is_absolute() or spec_path.resolve()!=(root/'jobs'/jid/'spec.json').resolve()
                or not out.is_absolute() or out.resolve()!=(root/'jobs'/jid/'attempts/attempt_001').resolve()
                or not auth.is_absolute() or sha(auth)!=entry['authorization_sha256']):
            raise ValueError('Recovery manifest entry path or authorization mismatch')
        evidence=validate_recovery(resume.read(spec_path),spec_path,out,auth)
        if (Path(evidence['terminated_namespace_evidence_path']).resolve()!=proof_path.resolve()
                or evidence['terminated_namespace_evidence_sha256']!=sha(proof_path)):
            raise ValueError('Recovery authorization bound to another termination proof')
    return dict(result,eligible=True,reason='ACP FAILED and exact namespace terminated; preserve started attempts, resume only authorized never-started claims',
        acp_state='FAILED',kind='failed_startup_namespace_terminated',uid=description['uid'],hostname=proof['hostname'],
        node_directory=str(node),retired_boot_id=proof['boot_id'],retired_pid_namespace=proof['pid_namespace'],
        bootstrap_exit=proof['exit_path'],bootstrap_exit_sha256=proof['exit_sha256'],
        bootstrap_path=proof['bootstrap_path'],bootstrap_sha256=proof['bootstrap_sha256'],
        terminated_namespace_evidence_path=str(proof_path),terminated_namespace_evidence_sha256=sha(proof_path),
        recovery_manifest_path=str(manifest),recovery_manifest_sha256=sha(manifest),
        pending=resume.pending_count(root,plan,job))


def replacement_once(receipts,job,evidence,dispatch,dispatch_path,stopping=lambda:False,invoke=create_cli):
    if stopping():return {'state':'stopping_no_create'}
    name=job['new_name'];directory=receipts/name
    argv=create_argv(job['submission'],name)
    try:directory.mkdir(parents=True,exist_ok=False)
    except FileExistsError:return {'state':'existing_request_never_repeated'}
    sources=['scripts/roll_sco_bc_v3_routes2_io3.py','scripts/roll_sco_bc_v3_rate_ops.py','scripts/bootstrap_bc_v3_node_routes2_io3.py',
             'scripts/replace_sco_bc_v3_after_reader_ops.py','scripts/resume_sco_bc_v3_after_reader_ops.py']
    request={'name':name,'replaces':job['name'],'original_name':job['original_name'],'generation':job['new_name'].rsplit('-',1)[1],
             'harness':job['harness'],'strategy':job['strategy'],'operation':'create','argv':argv,
             'requested_at':resume.now(),'requested_at_unix':time.time(),'evidence':evidence,
             'parent_receipt':{k:job[k] for k in ('parent_request','parent_response','parent_request_sha256','parent_response_sha256')},
             'operational_dispatch':dispatch,'dispatch_config':str(dispatch_path),'dispatch_config_sha256':sha(dispatch_path),
             'source_sha256':{**{p:sha(ROOT/p) for p in sources},**implementation_hashes(),**operational_record()['implementation_sha256']},'worker_ceiling':32,'active_workers_this_cell':16,
             'resources_image_mount_unchanged':True,'only_acp_argv_changes':['--job-name and --name: audited generation successor','--command bootstrap entry: io3 publication handling and exact never-started recovery authorization'],
             'route_plan_path':str(ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3/route-plan-v2.json'),
             'route_plan_sha256':sha(ROOT/'outputs/campaigns/bc100-r3-hermes-parity-v3/route-plan-v2.json'),
             'claim_policy':'Original campaign pending-only; no retry of claimed or old attempts',
             'automatic_repeat_allowed':False}
    resume.atomic(directory/'request.json',request)
    retirement={'hostname':evidence['hostname'],'boot_id':evidence['retired_boot_id'],
                'pid_namespace':evidence['retired_pid_namespace'],'job_name':job['name'],
                'retired_at':resume.now(),'retired_at_unix':time.time(),
                'reason':'Platform FAILED namespace termination independently verified; not a clean drain' if evidence.get('acp_state')=='FAILED' else 'ACP SUCCEEDED and bound clean drain before io3 controller rollout',
                'bootstrap_exit':evidence['bootstrap_exit'],'request_receipt':str(directory/'request.json')}
    retired_path=Path(evidence['node_directory'])/'retired.json'
    if retired_path.exists():
        old=resume.read(retired_path)
        if any(old.get(k)!=retirement[k] for k in ('hostname','boot_id','pid_namespace','job_name')):
            raise ValueError('Retirement identity conflicts; do not create')
    else:resume.atomic(retired_path,retirement)
    if stopping():response={'state':'not_sent_stopping','completed_at':resume.now()}
    elif (sha(dispatch_path)!=request['dispatch_config_sha256']
            or any(sha(ROOT/p)!=s for p,s in request['source_sha256'].items())
            or any(sha(Path(evidence[k]))!=evidence[k.removesuffix('_path')+'_sha256'] for k in
                ('terminated_namespace_evidence_path','recovery_manifest_path') if k in evidence)):
        response={'state':'not_sent_source_changed','completed_at':resume.now()}
    else:
        outcome=invoke(argv)
        response={'state':'submitted' if outcome.get('returncode')==0 else 'unknown' if outcome.get('returncode') is None else 'rejected',
                  'completed_at':resume.now(),**outcome}
    resume.atomic(directory/'response.json',response)
    return {'state':response['state'],'receipt':str(directory)}


def cycle(args,stopping=lambda:False,query=resume.cli,create=create_cli):
    plan=resume.read(args.root/'plan.json');dispatch=resume.read(args.dispatch_config)
    if (args.parent_generation,args.generation) not in (('ops4','ops5'),('ops5','ops6')):raise ValueError('Unsupported explicit route revision generation')
    if dispatch.get('active_workers_per_cloud_instance')!=16 or dispatch.get('local_target_workers')!=2:
        raise ValueError('Ops5 requires approved cloud16/local2 dispatch')
    route_plan=RoutePlan(args.root)
    if args.live:route_plan.bind()
    rows=[]
    for harness,strategy in resume.CELLS:
        if stopping():break
        if harness not in args.harness or strategy not in args.strategy:continue
        name='acl-bc-v3-'+harness+'-'+strategy.replace('_','-')+'-'+args.generation
        directory=args.receipts/name
        try:
            if directory.exists():
                response=resume.read(directory/'response.json') if (directory/'response.json').exists() else {'state':'unknown'}
                rows.append({'name':name,'state':response['state'],'automatic_repeat_allowed':False});continue
            if (LEGACY_VISUAL_RECEIPTS/name).exists():
                rows.append({'name':name,'state':'existing_other_receipt_never_repeated',
                             'receipt':str(LEGACY_VISUAL_RECEIPTS/name),'automatic_repeat_allowed':False});continue
            job=parent_job(args.submissions,harness,strategy,args.parent_generation,args.generation)
            if job is None:
                rows.append({'name':name,'eligible':False,'state':'awaiting_parent_submitted','reason':'Parent not independently confirmed submitted'});continue
            outcome=query(args.sco,'describe',job['name'])
            if outcome.get('returncode')!=0:
                rows.append({'name':name,'eligible':False,'reason':'Old ACP query failed'});continue
            description=json.loads(outcome['stdout'])
            row=assess_failed(args.root,plan,job,description) if description.get('state')=='FAILED' else parent.assess(args.root,plan,job,description)
            # The helper's identity/drain checks are generic; fix its historical labels.
            row['reason']=row.get('reason','').replace('ops3',args.generation).replace('ops2',args.parent_generation)
            if row.get('eligible'):
                existing=query(args.sco,'describe',name)
                if existing.get('returncode')==0:row.update(eligible=False,reason='Successor name already exists; never recreate')
                elif existing.get('returncode') is None or not error_reason(existing,'trainingJobNotFound'):
                    row.update(eligible=False,reason='New-name absence not proven')
                elif args.live:row['create']=replacement_once(args.receipts,job,row,dispatch,args.dispatch_config,stopping,create)
            rows.append(row)
        except (OSError,ValueError,KeyError,TypeError) as error:
            rows.append({'name':name,'eligible':False,'reason':'Incomplete evidence; no automatic create retry','error_type':type(error).__name__})
    return {'timestamp':resume.now(),'mode':'live' if args.live else 'dry_run','jobs':rows,'model_probes':0,
            'generation':args.generation,'dispatch':dispatch,'remote_signals_sent':0}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=resume.CAMPAIGN)
    parser.add_argument('--submissions',type=Path,default=ROOT/'outputs/cloud-runtime/routes1-replacements')
    parser.add_argument('--receipts',type=Path,default=ROOT/'outputs/cloud-runtime/routes2-replacements')
    parser.add_argument('--dispatch-config',type=Path,default=ROOT/'configs/cloud-dispatch-routes-v1.json')
    parser.add_argument('--sco',type=Path,default=ROOT/'.tools/sco-tj/cli/sco')
    parser.add_argument('--parent-generation',choices=['ops4','ops5'],default='ops5')
    parser.add_argument('--generation',choices=['ops5','ops6'],default='ops6')
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

