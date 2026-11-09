#!/usr/bin/env python3
"""Private, selected-attempt-bound answer-equivalence grading; SFB one request at a time."""
import argparse,collections,fcntl,json,os,signal,statistics,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from lab import ROOT,environment
import judge_bc_v3_completed as shared
from controlled_attempts_v5 import selection
from controlled_native_report_v4 import aggregate

VERSION='controlled-native-v4-private-grading-v1'
DEFAULT_ROOT=ROOT/'outputs/experiment3/controlled-native-v4'
DEFAULT_OUT=ROOT/'outputs/grading/controlled-native-v4-sfb-v1'
METHODS=('visual','summary','window');DATASETS=('browsecomp_v3','mmbrowsecomp')

def load(path):return json.loads(Path(path).read_text())
def resolve(root,entries,job):return Path(entries[job]['selected_out']) if job in entries else root/'jobs'/job

def group_gate(controls):
    if len(controls)!=3 or not all(c.get('passed') and c.get('native_identity_verified') for c in controls):return False
    counts=[c.get('first_actual_prompt_tokens') for c in controls]
    if not all(type(n) is int and 0<n<=16384 for n in counts):return False
    if not controls[0].get('native_hashes') or any(c.get('native_hashes')!=controls[0]['native_hashes'] for c in controls):return False
    if not controls[0].get('prefix_sha256') or controls[0].get('actual_route')!=shared.MODEL:return False
    if len({c.get('prefix_sha256') for c in controls})!=1 or len({c.get('actual_route') for c in controls})!=1:return False
    return (max(counts)-min(counts))/max(counts)<=.05

def protocol(root):
    manifest=load(ROOT/'outputs/cohorts/manifest.json');cohorts={}
    for ds in DATASETS:
        path=ROOT/'outputs/cohorts'/f'{ds}.jsonl';cohorts[ds]=shared.sha(path)
        if cohorts[ds]!=manifest['datasets'][ds]['cohort_sha256']:raise ValueError('Frozen gold cohort changed')
    return {'version':VERSION,'judge_model':shared.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':180,
        'concurrency':1,'root':str(root),'plan_sha256':shared.sha(root/'plan.json'),'config_sha256':shared.sha(root/'experiment.json'),
        'cohort_sha256':cohorts,'helper_version':shared.VERSION,
        'sources_sha256':{name:shared.sha(ROOT/'scripts'/name) for name in ('judge_controlled_native_v4.py','judge_bc_v3_completed.py','controlled_attempts_v4.py')},
        'judge_prompt_sha256':shared.sha(ROOT/'hermes-agent/Browsecomp_eval/browsecomp_eval/judge.py'),
        'prompt_definition':'Reuse the existing Hermes answer-equivalence prompt/parser used for these local datasets; not an asserted separate official MMBrowseComp checklist score',
        'selected_attempt_policy':'Explicit ops2 selection is fixed before grading, otherwise original result; never choose based on score',
        'api_retry_policy':'One HTTP operation per selected completed result; started/error/unknown/invalid never automatically retried',
        'answer_isolation':'Gold and judge request/response remain only in this private grading namespace; never written into native workspaces',
        'dollars':None,'mean_std_policy':'Only after all planned dataset arms terminal and all completed matched-subset predictions graded; report matched-subset repeat accuracy, with matched terminal unsuccessful trajectories counted zero and coverage retained'}

def inventory(root,output,config):
    if shared.sha(root/'plan.json')!=config['plan_sha256'] or shared.sha(root/'experiment.json')!=config['config_sha256']:raise ValueError('Campaign lineage changed')
    plan=load(root/'plan.json');entries=selection(root);cohorts={}
    for ds in DATASETS:
        path=ROOT/'outputs/cohorts'/f'{ds}.jsonl'
        if shared.sha(path)!=config['cohort_sha256'][ds]:raise ValueError('Gold cohort changed')
        cohorts[ds]={r['id']:r for r in (json.loads(line) for line in path.read_text().splitlines())}
    controls={};groups={}
    for p in plan['prefixes']:
        rows=[]
        for method in METHODS:
            job=p['key']+'/'+method;path=resolve(root,entries,job)/'compression-control.json'
            control=load(path) if path.exists() else {};controls[job]=control;rows.append(control)
        groups[p['key']]=group_gate(rows)
    candidates=[];records=[];cells=collections.defaultdict(list);grader_rows=[]
    for job in plan['jobs']:
        jobid=job['job_id'];source=resolve(root,entries,jobid);result_path=source/'result.json';spec=load(source/'spec.json')
        dataset=job['dataset'];row=cohorts[dataset][spec['question_id']]
        if row['question']!=spec['question']:raise ValueError('Question/gold binding mismatch')
        if spec['model']!=shared.MODEL:raise ValueError('Controlled grading source uses an unexpected route')
        state=load(result_path) if result_path.exists() else {};terminal=bool(state)
        control=controls[jobid];matched=groups[job['prefix_key']]
        item={'job_id':jobid,'dataset':dataset,'method':job['method'],'repeat':spec['repeat'],'status':state.get('status','pending'),
            'terminal':terminal,'matched_group_gate':matched,'individual_gate':bool(control.get('passed') and control.get('native_identity_verified')),'grade_status':None,'score':None}
        destination=output/'jobs'/jobid/(Path(entries[jobid]['selected_out']).name if jobid in entries else 'original')
        if state.get('status')=='completed':
            conversation_path=source/'conversation.json';conversation=load(conversation_path);prediction=conversation.get('final_response') or ''
            if not isinstance(prediction,str):raise ValueError('Completed prediction is not a string')
            prefix=Path(spec['prefix_path']);spec_path=source/'spec.json';control_path=source/'compression-control.json'
            if control.get('prefix_sha256')!=shared.sha(prefix):raise ValueError('Completed prefix/control mismatch')
            binding={'baseline_grading_version':VERSION,'root':str(root),'job_id':jobid,'question_id':spec['question_id'],'dataset':dataset,'method':job['method'],'repeat':spec['repeat'],
                'attempt_path':str(source),'result_path':str(result_path),'result_sha256':shared.sha(result_path),
                'conversation_path':str(conversation_path),'conversation_sha256':shared.sha(conversation_path),
                'spec_path':str(spec_path),'spec_sha256':shared.sha(spec_path),'prefix_path':str(prefix),'prefix_sha256':shared.sha(prefix),
                'control_path':str(control_path),'control_sha256':shared.sha(control_path),'prediction_sha256':shared.sha_bytes(prediction.encode()),
                'question_sha256':shared.sha_bytes(row['question'].encode()),'cohort_sha256':config['cohort_sha256'][dataset],
                'selection_entry_sha256':shared.sha_bytes(json.dumps(entries[jobid],sort_keys=True).encode()) if jobid in entries else None}
            if (destination/'binding.json').exists() and load(destination/'binding.json')!=binding:raise ValueError('Previously bound selected result changed')
            if (destination/'grade.json').exists():
                grade=load(destination/'grade.json')
                if any(grade.get(k)!=v for k,v in binding.items()):raise ValueError('Grade/source binding mismatch')
                item.update(grade_status=grade['status'],score=grade.get('score'))
                if grade.get('api_calls')!=0:grader_rows.append(dict(grade,client_stream_seconds=grade.get('client_http_seconds')))
            elif (destination/'request-started.json').exists():
                item['grade_status']='unknown_no_automatic_retry';grader_rows.append(load(destination/'request-started.json'))
            else:
                candidates.append({'directory':destination,'binding':binding,'question':row['question'],'answer':row['answer'],'prediction':prediction})
                item['grade_status']='pending_grade'
        records.append(item);cells[dataset+'/'+job['method']].append(item)
    summaries={}
    for cell,rows in cells.items():
        dataset=cell.split('/')[0];matched=[r for r in rows if r['matched_group_gate']]
        completed=[r for r in matched if r['status']=='completed'];scored=[r for r in completed if r['grade_status']=='scored']
        final=all(r['terminal'] for r in records if r['dataset']==dataset) and len(scored)==len(completed)
        means=[];denominators={}
        for repeat in (1,2,3):
            eligible=[r for r in matched if r['repeat']==repeat];denominators[str(repeat)]=len(eligible)
            if final and eligible:means.append(sum(r['score'] or 0 for r in eligible)/len(eligible))
        summaries[cell]={'planned':len(rows),'selected_terminal':sum(r['terminal'] for r in rows),'completed':sum(r['status']=='completed' for r in rows),
            'matched_valid_gate':len(matched),'matched_completed':len(completed),'matched_completed_scored':len(scored),
            'grade_coverage':len(scored)/len(completed) if completed else None,'all_completed_scored':sum(r['grade_status']=='scored' for r in rows),
            'mean_repeat_accuracy_matched_subset':statistics.mean(means) if len(means)==3 else None,
            'std_repeat_accuracy_matched_subset':statistics.stdev(means) if len(means)==3 else None,'matched_denominator_by_repeat':denominators}
    return candidates,{'at':shared.now(),'planned':len(plan['jobs']),'selected_terminal':sum(r['terminal'] for r in records),
        'ready_to_grade':len(candidates),'matched_prefix_groups':sum(groups.values()),'planned_prefix_groups':len(groups),
        'by_cell':summaries,'judge_usage_separate':aggregate(grader_rows),'records':records,'gold_in_report':False}

def grade_bound(candidate,config,env,opener=None):
    binding=candidate['binding']
    for name in ('result','conversation','spec','prefix','control'):
        if shared.sha(binding[name+'_path'])!=binding[name+'_sha256']:raise ValueError('Bound '+name+' changed before grading')
    kwargs={'opener':opener} if opener is not None else {}
    return shared.grade(candidate,config,env,**kwargs)

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--root',type=Path,default=DEFAULT_ROOT);ap.add_argument('--output',type=Path,default=DEFAULT_OUT)
    ap.add_argument('--live',action='store_true');ap.add_argument('--watch',action='store_true');a=ap.parse_args()
    root=a.root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True);out.chmod(0o700)
    if out.is_relative_to(root):raise ValueError('Private grading output must be outside native campaign')
    cfg=protocol(root);shared.immutable(out/'protocol.json',cfg)
    shared.atomic(out/'runtime-selection-v5.json',{'version':'controlled-v5-selected-grading','source_sha256':shared.sha(Path(__file__)),'selection_helper_sha256':shared.sha(ROOT/'scripts/controlled_attempts_v5.py'),'selection_sha256':shared.sha(root/'attempt-selection-ops3.json'),'unchanged_judge_protocol':True,'existing_bound_grades_reused':True})
    candidates,summary=inventory(root,out,cfg);shared.atomic(out/'summary.json',summary)
    if not a.live:print(json.dumps({'live':False,'completed_ready':len(candidates),'concurrency':1,'model':shared.MODEL}));return
    env,_=environment(ROOT,'dsh',root/'experiment.json');lease=(out/'controller.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    stopped=False
    def stop(*unused):
        nonlocal stopped
        stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=None;next_scan=0
        while True:
            if future and future.done():
                try:future.result()
                except Exception as exc:shared.atomic(out/'local-error.json',{'at':shared.now(),'error_type':type(exc).__name__})
                future=None;next_scan=0
            if future is None and not stopped and time.time()>=next_scan:
                candidates,summary=inventory(root,out,cfg);shared.atomic(out/'summary.json',summary);next_scan=time.time()+30
                if candidates:future=pool.submit(grade_bound,candidates[0],cfg,env)
            shared.atomic(out/'status.json',{'at':shared.now(),'pid':os.getpid(),'active_requests':int(future is not None),'concurrency':1,'stopping':stopped,'native_calls':0,'purpose':'judge','selected_terminal':summary['selected_terminal']})
            if future is None and (stopped or not a.watch):break
            time.sleep(2)
if __name__=='__main__':main()
