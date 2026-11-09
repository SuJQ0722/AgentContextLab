#!/usr/bin/env python3
"""One first native launch for q045r02 after exact stopped dispatcher fully drains."""
import argparse,json,time,subprocess,sys,signal
from pathlib import Path
import run_rq3_scale_cloud_ops2 as base
import run_rq3_scale0700_resume_ops5 as pending
import run_rq3_scale0700_paid_retry1 as paid
from run_bc_campaign_v3 import owner_alive,atomic
from bc_route_runtime_v2 import immutable_json
from lab import ROOT

VERSION='rq3-pre-native-reservation-recovery3'
JOB='hermes/scale_0700/q_045_r02'
DEFAULT_ROOT=ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery3'
GRADING=ROOT/'outputs/grading/rq3-parity-v3-pre-native-recovery3'
MANIFEST='recovery-authorization.json'
SOURCE_NAMES=('recover_rq3_pre_native_third_once.py','run_rq3_pre_native3_trial.py','judge_rq3_pre_native3.py','report_rq3_final_seven_v3.py','run_rq3_scale0700_paid_retry1.py','report_rq3_final_seven_v2.py')
ORIGINAL_JOBS=base.jobs_for_scale
ORIGINAL_PUBLISH=base.publish_claim


def area(root):return Path(root)/'pre-native-recovery3-ops'
def read(p):return base.scientific.read(p)
def sha(p):return base.scientific.sha(p)


def no_native(attempt):
    names={p.name for p in Path(attempt).iterdir()}
    if names-{'cloud-scale-dispatch-ops2.json','result.json'}:raise ValueError('Original reserved attempt has native or unknown artifacts')


def prepare(parent,root,grading=GRADING):
    parent=Path(parent).resolve();root=Path(root).resolve();grading=Path(grading).resolve()
    if parent==root or grading.is_relative_to(root):raise ValueError('Separate prediction/grading roots required')
    parent_authorization=pending.verify_authorization(parent)
    if JOB not in parent_authorization['pending_job_ids']:raise ValueError('Held job was not in original pending219 authorization')
    handoff=pending.area(parent)/'handoffs/local-to-cloud1';held=read(handoff/'held-reservation.json');ready=read(handoff/'held-ready.json');request=read(handoff/'request.json')
    if held.get('job_id')!=JOB or held.get('native_never_started_at_checkpoint') is not True or ready.get('held_reservation_sha256')!=sha(handoff/'held-reservation.json'):
        raise ValueError('Held reservation handoff proof differs')
    original=read(parent/'plan.json');base.scientific.validate(original,parent);job=next(j for j in original['jobs'] if j['job_id']==JOB)
    d=parent/'jobs'/JOB;a=d/'attempts/attempt_001';no_native(a);claim=read(d/'claim/owner.json');spec=read(d/'spec.json')
    if any(spec.get(k)!=v for k,v in job.items()) or spec.get('plan_sha256')!=sha(parent/'plan.json'):raise ValueError('Original specification differs')
    for k in ('hostname','boot_id','pid_namespace','controller_id','pid','start_identity'):
        if claim.get(k)!=held['original_controller'].get(k):raise ValueError('Original held owner differs')
    for name in ['experiment.json','cohort.jsonl',*original['definition']['scale_config_sha256']]:paid.copy_once(parent/name,root/name)
    plan=json.loads(json.dumps(original))
    for j in plan['jobs']:j['config_path']=str(root/Path(j['config_path']).relative_to(parent))
    plan['definition']['jobs_sha256']=pending.object_sha(plan['jobs']);plan['definition']['pre_native_recovery3']={'version':VERSION,'authorized_jobs':[JOB],'parent_root':str(parent),'parent_plan_sha256':sha(parent/'plan.json'),'scientific_change':False,'placeholders_not_authorized':2099}
    immutable_json(root/'plan.json',plan)
    auth={'version':VERSION,'launch_authorized_after_exact_exit':True,'parent_root':str(parent),'recovery_root':str(root),'grading_root':str(grading),
          'parent_plan_sha256':sha(parent/'plan.json'),'recovery_plan_sha256':sha(root/'plan.json'),'authorized_job_ids':[JOB],'max_first_native_launches':1,
          'original_owner':held['original_controller'],'original_run':request['old_run'],'original_slot_path':held['slot_path'],
          'entries':[{'job_id':JOB,'parent_attempt':str(a),'retry_attempt':str(root/'jobs'/JOB/'attempts/attempt_001'),'parent_spec_sha256':sha(d/'spec.json'),'parent_claim_sha256':sha(d/'claim/owner.json')}],
          'proof_files_sha256':{str(handoff/n):sha(handoff/n) for n in ['request.json','held-reservation.json','held-ready.json','stop-ack.json']},
          'source_sha256':{str(ROOT/'scripts'/n):sha(ROOT/'scripts'/n) for n in SOURCE_NAMES},
          'shared_slot_root':str(pending.area(parent)/'slots'/pending.LABEL),'shared_scale_ceiling':16,
          'selection':'Always select this first native recovery for the same question/repeat; original must prove api_calls0. No extra seed or score-based choice.'}
    immutable_json(root/MANIFEST,auth);immutable_json(area(root)/'cutover.json',auth);return auth


def validate_scope(root):
    root=Path(root).resolve();a=read(root/MANIFEST);parent=Path(a['parent_root']);pending.verify_authorization(parent)
    if a.get('version')!=VERSION or a.get('launch_authorized_after_exact_exit') is not True or a.get('authorized_job_ids')!=[JOB] or a.get('max_first_native_launches')!=1 or a.get('shared_scale_ceiling')!=16 or Path(a['recovery_root'])!=root:raise ValueError('Invalid single recovery scope')
    if sha(parent/'plan.json')!=a['parent_plan_sha256'] or sha(root/'plan.json')!=a['recovery_plan_sha256']:raise ValueError('Recovery scientific source changed')
    for p,h in {**a['proof_files_sha256'],**a['source_sha256']}.items():
        if sha(p)!=h:raise ValueError('Bound recovery implementation/evidence changed')
    e=a['entries'][0];d=parent/'jobs'/JOB;original=d/'attempts/attempt_001';no_native(original)
    if len(a['entries'])!=1 or e['job_id']!=JOB or Path(e['parent_attempt'])!=original or Path(e['retry_attempt'])!=root/'jobs'/JOB/'attempts/attempt_001':raise ValueError('Recovery mapping differs')
    if sha(d/'spec.json')!=e['parent_spec_sha256'] or sha(d/'claim/owner.json')!=e['parent_claim_sha256']:raise ValueError('Original reservation changed')
    if Path(a['shared_slot_root'])!=pending.area(parent)/'slots'/pending.LABEL or read(area(root)/'cutover.json')!=a:raise ValueError('Capacity/cutover changed')
    plan=read(root/'plan.json');base.scientific.validate(plan,root);return plan,a


def exit_proof(a):
    original=Path(a['entries'][0]['parent_attempt']);no_native(original);owner=a['original_owner']
    if owner_alive(owner) is not False:return None,'waiting_exact_original_controller_exit'
    run=Path(a['original_run']);ep=run/'exit.json';rp=original/'result.json'
    if not ep.exists() or not rp.exists():return None,'waiting_durable_exit_and_not_started_result'
    end=read(ep);result=read(rp)
    if any(end.get(k)!=owner.get(k) for k in ('hostname','boot_id','pid_namespace','controller_id','pid','start_identity')) or end.get('drained') is not True or end.get('stopped') is not True:
        raise ValueError('Original dispatcher did not prove drained exact exit')
    if not(result.get('job_id')==JOB and result.get('status')=='not_started' and result.get('api_calls')==0 and result.get('slot_released') is True and result.get('unconfirmed_child_termination')==[] and result.get('failure_category')=='cloud_controller_stopped_before_native_launch'):
        raise ValueError('Original result is not explicit zero-API never-started')
    sp=Path(a['original_slot_path'])/'owner.json'
    if sp.exists():
        slot=read(sp)
        if slot.get('controller_id')==owner['controller_id'] and slot.get('job_id')==JOB:raise ValueError('Old reserved slot still held')
    return {'exact_owner_dead':True,'native_never_started':True,'exit_path':str(ep),'exit_sha256':sha(ep),'result_path':str(rp),'result_sha256':sha(rp),'api_calls':0},'ready'


def install(root):
    root=Path(root).resolve();plan,a=validate_scope(root);proof,state=exit_proof(a)
    if proof is None:raise ValueError('First native launch gated: '+state)
    immutable_json(root/'never-started-proof.json',proof);parent=Path(a['parent_root']);pa=pending.verify_authorization(parent)
    def jobs(p,scale):
        if base.normalize_scale(scale)!=pending.LABEL:raise ValueError('Wrong scale')
        return [j for j in ORIGINAL_JOBS(p,scale) if j['job_id']==JOB]
    def publish(r,job,owner,scale,cap=1):
        _,authorization=validate_scope(r);ready,_=exit_proof(authorization)
        if ready is None or job['job_id']!=JOB:raise ValueError('Not authorized to launch')
        return ORIGINAL_PUBLISH(r,job,owner,scale,cap)
    base.area=area;base.VERSION=VERSION;base.jobs_for_scale=jobs;base.verify_cutover=lambda r:validate_scope(r)[1]
    base.acquire_scale_slot=paid.parent_slot_allocator(parent,pa);base.publish_claim=publish;return a


def dispatch(root,popen=subprocess.Popen):
    root=Path(root).resolve();install(root)
    def spawn(command,**kwargs):
        old=str(ROOT/'scripts/run_rq3_parity_trial.py');new=str(ROOT/'scripts/run_rq3_pre_native3_trial.py')
        if command.count(old)!=1:raise ValueError('Unexpected trial')
        return popen([new if s==old else s for s in command],**kwargs)
    base.controller(root,pending.LABEL,1,popen=spawn)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--parent',type=Path,default=base.scientific.DEFAULT_ROOT);p.add_argument('--grading',type=Path,default=GRADING)
    p.add_argument('--prepare',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');args=p.parse_args()
    a=prepare(args.parent,args.root,args.grading) if args.prepare else validate_scope(args.root)[1]
    if not args.live:
        proof,state=exit_proof(a);print(json.dumps({'live':False,'state':state,'authorized_first_native_launches':1}));return
    import fcntl
    args.root.mkdir(parents=True,exist_ok=True);lock=(args.root/'recovery-watch.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stopped=False
    def stop(*unused):
        # No children exist until base.controller installs its drain handlers.
        # Exit immediately here so an early stop cannot be lost during startup.
        raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    while not stopped:
        _,a=validate_scope(args.root);proof,state=exit_proof(a);atomic(args.root/'waiting-status.json',{'at':time.time(),'state':state,'native_calls_added':0})
        if proof:dispatch(args.root);return
        if not args.watch:return
        time.sleep(3)

if __name__=='__main__':main()
