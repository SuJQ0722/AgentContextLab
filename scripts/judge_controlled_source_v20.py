"""Private, first-judgment-only scorer for the two source-prefix text arms.

A completion is eligible only after the source, native bytes, measured total
budget and final wire checks all pass. Reuse/blocked slots make no judge call.
"""
import argparse
from collections import Counter, defaultdict
import fcntl
import io
import json
import math
from pathlib import Path
import signal
import time
import urllib.error
import httpx

from lab import ROOT, environment
import judge_bc_v3_completed as bc
from judge_visual_hosted_retry_v1 import gold_sources
from judge_controlled_single_pass_v14 import measured_costs
from judge_once_queue_io_v16 import run_queue, LatestStatusWriter
from controlled_mmbc_source_v20 import DEFAULT, DEADLINE, read, sha, save, validate_plan, validate_job
from report_once24h_v15 import repeat_statistics

OUT=ROOT/'outputs/grading/controlled-mmbc-vera-nontimeout-v20'


def valid_control(control, target):
    actual=control.get('first_actual_prompt_tokens'); expected=target.get('source_first_post_prompt_tokens')
    return bool(control.get('passed') is True and control.get('native_identity_verified') is True
        and control.get('final_wire_native_identity_preserved') is True
        and control.get('image_token_parity_claimed') is False
        and control.get('prefix_sha256') == target.get('prefix_sha256')
        and control.get('native_hashes') == target.get('baseline_native_hashes')
        and type(actual) is int and type(expected) is int and expected>0
        and math.ceil(.98*expected)<=actual<=math.floor(1.02*expected))


class Inventory:
    def __init__(self, root, out):
        self.root=Path(root);self.out=Path(out);self.plan=read(root/'plan.json');validate_plan(root,self.plan)
        self.plan_sha=sha(root/'plan.json');self.gold,self.gold_hashes=gold_sources();self.done_validation=set()
    def scan(self, with_cost=False):
        if sha(self.root/'plan.json')!=self.plan_sha:raise ValueError('Frozen plan changed')
        rows=[];pending=[]
        for job in self.plan['jobs']:
            attempt=Path(job['output_path']);terminal_path=attempt/'terminal.json'
            terminal=read(terminal_path) if terminal_path.exists() else {}
            dest=self.out/'jobs'/job['job_id'];row={k:job[k] for k in ('job_id','question_id','repeat','method','action','source_result_sha256')}
            row.update(status=terminal.get('status','pending'),score=None,control_valid=False,
                new_attempts=terminal.get('new_attempts'),native_cleanup_confirmed=terminal.get('native_cleanup_confirmed'))
            if terminal:
                if any(terminal.get(k)!=job[k] for k in ('job_id','question_id','repeat','method','source_result_sha256')):raise ValueError('Terminal identity changed')
                if with_cost and terminal.get('new_attempts')==1:
                    cost=dest/'prediction-accounting.json'
                    if not cost.exists():save(cost,measured_costs(attempt))
                    row['prediction_accounting_path']=str(cost)
            if terminal.get('status')=='completed' and terminal.get('native_cleanup_confirmed') is True and job['action']=='matched_continuation':
                native_path=attempt/'native-result.json';control_path=attempt/'compression-control.json'
                native=read(native_path);control=read(control_path);target=read(job['target_path'])
                valid=(native.get('status')=='completed' and native.get('job_id')==job['job_id']
                    and native.get('source_result_sha256')==job['source_result_sha256']
                    and native.get('spec_sha256')==job['spec_sha256']
                    and valid_control(control,target) and valid_control(native.get('control_gate') or {},target))
                row.update(control_valid=valid,actual_prompt_tokens=control.get('first_actual_prompt_tokens'),
                    source_prompt_tokens=target['source_first_post_prompt_tokens'],image_token_parity_claimed=False)
                if valid:
                    if job['job_id'] not in self.done_validation:validate_job(job);self.done_validation.add(job['job_id'])
                    spec=read(job['spec_path']);secret=self.gold['mmbc'][job['question_id']]
                    if spec['question']!=secret['question']:raise ValueError('Private gold question differs')
                    binding={'version':'controlled-source-private-judge-v20','job_id':job['job_id'],
                        'question_id':job['question_id'],'repeat':job['repeat'],'method':job['method'],
                        'plan_sha256':self.plan_sha,'result_path':str(native_path),'result_sha256':sha(native_path),
                        'control_sha256':sha(control_path),'target_sha256':sha(job['target_path']),
                        'source_result_sha256':job['source_result_sha256'],'spec_sha256':job['spec_sha256'],
                        'question_sha256':bc.sha_bytes(secret['question'].encode()),'gold_sources_sha256':self.gold_hashes}
                    gp=dest/'grade.json'
                    if gp.exists():
                        grade=read(gp)
                        if any(grade.get(k)!=v for k,v in binding.items() if k!='version'):raise ValueError('Grade source binding differs')
                        row['grade_status']=grade.get('status')
                        if grade.get('status')=='scored' and grade.get('score') in (0,1):row['score']=grade['score'];row['grade_path']=str(gp)
                    if not any((dest/name).exists()for name in ('request-started.json','grade.json','local-error.json')):
                        pending.append({'directory':dest,'binding':binding,'question':secret['question'],
                            'answer':secret['answer'],'prediction':native['final']['text']})
            rows.append(row)
        methods=[]
        for method in ('summary','window'):
            rr=[r for r in rows if r['method']==method]
            methods.append({'method':method,'cohort_slots':len(rr),'states':dict(Counter(r['status']for r in rr)),
                'matched_continuation_scored':repeat_statistics(rr),'image_token_parity_claimed':False})
        groups=defaultdict(dict)
        for row in rows:groups[(row['question_id'],row['repeat'])][row['method']]=row
        paired=[{'question_id':key[0],'repeat':key[1], 'summary_score':g['summary']['score'],'window_score':g['window']['score']}
            for key,g in groups.items() if set(g)=={'summary','window'} and all(v.get('score') in (0,1) and v.get('control_valid') for v in g.values())]
        report={'version':'controlled-source-private-report-v20','at':time.time(),'plan_sha256':self.plan_sha,
            'rows':rows,'methods':methods,'paired_text_arms':paired,'pending_judges':len(pending),
            'cohort_slots':self.plan['cohort_slots'],'benchmark_denominator':300,'source_prefix_single_intervention':True,
            'full_benchmark_avg3_claimed':False,'reuse_is_not_new_measurement':True,'blocked_and_unknown_not_zero':True,
            'image_token_parity_claimed':False,'budget_rule':'Total provider prompt tokens +/-2%; VERA embeds images, controls preserve native separately.'}
        save(self.out/'report.json',report)
        all_terminal=all(r['status']!='pending' for r in rows)
        return pending,{'all_terminal':all_terminal,'methods':methods}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT);p.add_argument('--out',type=Path,default=OUT);p.add_argument('--live',action='store_true');args=p.parse_args()
    root=args.root.resolve();out=args.out.resolve()
    if root!=DEFAULT or out!=OUT or root in out.parents:raise ValueError('Private grading scope changed')
    out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
    lock=(out/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    inv=Inventory(root,out);cfg={'judge_model':'deepseek-v4.1-flash-1017/huoshan/huoshan','max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':180}
    bc.immutable(out/'protocol.json',{'version':'controlled-source-private-judge-v20','plan_sha256':inv.plan_sha,
        'gold_sha256':inv.gold_hashes,'config':cfg,'concurrency':4,'retry':0,'source_sha256':sha(__file__),
        'hermes_judge_sha256':sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py'),
        'scientific_scoring':'Existing answer equivalence prompt; first judgment only; exact source/native/total-budget eligibility.'})
    if not args.live:
        candidates,status=inv.scan();save(out/'dry-validation.json',{'model_calls':0,'ready':len(candidates),'plan_sha256':inv.plan_sha,'protocol_sha256':sha(out/'protocol.json')});print({'model_calls':0,'ready':len(candidates),**status});return
    receipt=read(out/'dry-validation.json')
    if receipt['model_calls']!=0 or receipt['plan_sha256']!=inv.plan_sha or receipt['protocol_sha256']!=sha(out/'protocol.json'):raise ValueError('Dry binding differs')
    env,_=environment(ROOT,'hermes');stopped=False
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    def opener(request,timeout):
        with httpx.Client(proxy=env.get('HTTPS_PROXY')or env.get('https_proxy'),trust_env=False,timeout=timeout) as client:
            response=client.post(request.full_url,content=request.data,headers=dict(request.header_items()))
        if response.status_code>=400:raise urllib.error.HTTPError(request.full_url,response.status_code,'Provider error',response.headers,io.BytesIO(response.content))
        stream=io.BytesIO(response.content);stream.status=response.status_code;stream.headers=response.headers;return stream
    def grade(candidate):return bc.grade(candidate,cfg,env,opener=opener)
    def error(candidate,exc):save(Path(candidate['directory'])/'local-error.json',{'at':time.time(),'error_type':type(exc).__name__,'retry':False})
    writer=LatestStatusWriter(lambda row:save(out/'status.json',{'at':time.time(),**row}))
    try:result=run_queue(inv.scan,grade,error,writer.publish,stop=lambda:stopped or time.time()>=DEADLINE,concurrency=4)
    finally:writer.close()
    inv.scan(True);save(out/'status.json',{'at':time.time(),'finished':True,'active':0,**result})

if __name__=='__main__':main()
