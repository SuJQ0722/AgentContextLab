"""Read-only fixed-cohort reporting; no model calls, prediction mutations, or log walks."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import os
import statistics
import time

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = Path('/mnt/data/acl-once24h-20261113/full-slot-manifest.json')
DEFAULT_MAP = ROOT/'outputs/cloud-runtime/deepseek-once24h-v15/grading-map.json'
DEFAULT_OUT = ROOT/'outputs/reports/once24h-v15'
DEADLINE = datetime.fromisoformat('2026-11-14T19:20:06+00:00').timestamp()
BUDGET = {'step_limit','output_limit','context_limit','context_length_exceeded','task_budget_exhausted'}
IDENTITY = ('job_id','harness','strategy','question_id','repeat','model')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp-'+str(os.getpid()))
    tmp.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False,indent=2))
    tmp.replace(path)


def timestamp(value):
    if isinstance(value,(int,float)): return float(value)
    if isinstance(value,str):
        try: return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
        except ValueError: pass
    return None


def clean(result):
    return result.get('native_cleanup_confirmed') is True or (result.get('slot_released') is True and result.get('unconfirmed_child_termination') == [])


def matching_grade(grade, result_sha, question_sha, repeat):
    return (grade.get('status')=='scored' and grade.get('score') in (0,1)
            and grade.get('result_sha256')==result_sha
            and grade.get('question_sha256')==question_sha
            and str(grade.get('repeat'))==str(repeat))


def choose_completed(candidates):
    # Correctness is deliberately absent from the ordering key.
    completed=[r for r in candidates if r.get('status')=='completed' and r.get('identity_valid') and r.get('cleanup_confirmed')]
    return min(completed,key=lambda r:(r.get('finished_unix') or 0,r.get('baseline_priority',1),r['result_path'])) if completed else None


def repeat_statistics(rows, score_field='score'):
    repeats=[]
    for repeat in (1,2,3):
        values=[r[score_field] for r in rows if r['repeat']==repeat and r.get(score_field) in (0,1)]
        repeats.append({'repeat':repeat,'valid_n':len(values),'correct':sum(values),'accuracy':statistics.mean(values) if values else None})
    rates=[r['accuracy']for r in repeats]
    return {'repeats':repeats,'valid_n':sum(r['valid_n']for r in repeats),
            'mean':statistics.mean(rates) if all(v is not None for v in rates) else None,
            'sample_std':statistics.stdev(rates) if all(v is not None for v in rates) else None}


def replay_flags(new_paths, reserved_intersecting_paths):
    paths=set(new_paths)|set(reserved_intersecting_paths)
    return {'observed_this_pass_attempt_paths':sorted(paths),'replay_detected':len(paths)>1}


class Reporter:
    def __init__(self, baseline, grading_map, output, workers=8):
        self.output=Path(output);self.workers=workers;self.immutable={};self.hashes={};self.errors=[]
        self.base=self.read(baseline,stable=True);self.mapping=self.read(grading_map,stable=True)
        if len(self.base['slots'])!=6900:raise ValueError('Expected all 6900 DeepSeek slots')
        self.cutoff=self.base['cutoff_unix'];self.new={j['slot_id']:j for j in self.mapping['jobs']}
        if set(self.new)!=set(self.base['eligible_slot_ids']):raise ValueError('Prediction mapping differs from authorized missing slots')
        self.slots={r['slot_id']:r for r in self.base['slots']};self.plan_cache={};self.grade_paths=defaultdict(set)
        self.result_grade_paths=defaultdict(set);self.grade_bindings=defaultdict(list)
        self.bound_sources={'baseline':str(baseline),'baseline_sha256':self.hashes[str(Path(baseline))],
                            'grading_map':str(grading_map),'grading_map_sha256':self.hashes[str(Path(grading_map))]}
        self.load_grade_index()

    def read(self,path,stable=False):
        path=Path(path);key=str(path)
        if key in self.immutable:return self.immutable[key]
        try:raw=path.read_bytes();value=json.loads(raw)
        except FileNotFoundError:return None
        except (OSError,ValueError) as e:
            self.errors.append({'path':key,'error_type':type(e).__name__});return None
        self.hashes[key]=digest(raw)
        if stable or (isinstance(value,dict)and value.get('status')=='scored'):self.immutable[key]=value
        return value

    def load_grade_index(self):
        seed_path=Path('/mnt/data/acl-rebuttal-20261113/selected-private.json')
        seed=self.read(seed_path,stable=True)or[]
        for r in seed:
            if r.get('grade_path')and r.get('result_sha256'):self.grade_paths[r['result_sha256']].add(r['grade_path'])
        audit=self.read(Path('/mnt/data/acl-once24h-20261113/judge-coverage-audit.json'),stable=True)or{}
        for r in audit.get('rows',[]):
            for g in r.get('matching_grade_records',[]):self.grade_paths[r['result_sha256']].add(g['grade_path'])
            for g in r.get('live_coverage',[]):self.grade_paths[r['result_sha256']].add(g['grade_path'])
        for name in ('connection-failure-recovery-v13','uncovered-once-v15'):
            p=ROOT/'outputs/grading'/name/'manifest.json';m=self.read(p,stable=True)or{}
            for r in m.get('records',[]):
                sha=r.get('result_sha256')or r.get('prediction_result_sha256')
                if sha:self.grade_paths[sha].add(r['new_grade'])
        for j in self.new.values():self.result_grade_paths[j['prediction_result_path']].add(j['grade_path'])
        for grading in (ROOT/'outputs/grading').iterdir():
            for p in (grading/'cells').glob('*/source-binding.json'):
                b=self.read(p,stable=True)
                if b:self.grade_bindings[p.parent.name].append((p.parent,Path(b['root'])))

    def expected_job(self,path):
        root=Path(str(path).split('/jobs/')[0]);jobid=str(path).split('/jobs/',1)[1].split('/attempts/',1)[0]
        if str(root)not in self.plan_cache:
            plan=self.read(root/'plan.json',stable=True)
            self.plan_cache[str(root)]={j['job_id']:j for j in plan['jobs']}if plan else{}
        return self.plan_cache[str(root)].get(jobid)

    def result(self,path,slot,baseline=False,expected_sha=None):
        value=self.read(path,stable=baseline)
        if value is None:return None
        h=self.hashes[str(Path(path))]
        if expected_sha and h!=expected_sha:raise ValueError('Immutable baseline result changed: '+str(path))
        job=self.expected_job(path)
        identity_valid=bool(job)and all(value.get(k)==job[k]for k in IDENTITY)
        if job:identity_valid &= digest(job['question'].encode())==slot['question_sha256']
        return {'result_path':str(path),'result_sha256':h,'status':value.get('status'),'identity_valid':identity_valid,
                'cleanup_confirmed':clean(value),'failure_category':value.get('failure_category'),
                'finished_unix':timestamp(value.get('finished_at'))or timestamp(value.get('finished_at_unix')),
                'end_to_end_seconds':value.get('end_to_end_seconds'),'baseline_priority':0 if baseline else 1,
                'value':value}

    def grade(self,result,slot):
        h=result['result_sha256'];paths=set(self.grade_paths[h])|self.result_grade_paths[result['result_path']]
        rp=Path(result['result_path']);root=Path(str(rp).split('/jobs/')[0]);jobid=str(rp).split('/jobs/',1)[1].split('/attempts/',1)[0]
        for gradecell,source in self.grade_bindings.get(root.name,[]):
            bound=source/'jobs'/jobid/'attempts/attempt_001/result.json'
            if bound.resolve()==rp.resolve()or source.resolve()==root.resolve():paths.add(str(gradecell/'jobs'/jobid/'grade.json'))
        for p in sorted(paths):
            g=self.read(p)
            if g and matching_grade(g,h,slot['question_sha256'],slot['repeat']):
                return float(g['score']),str(p),self.hashes[str(Path(p))]
        return None,None,None

    def run_intersects(self,run):
        result=self.read(run/'result.json')
        start=timestamp((result or{}).get('started_at_unix_estimate')) or timestamp((result or{}).get('started_at')) or timestamp((result or{}).get('started_at_unix'))
        if start is None:
            started=self.read(run/'worker-started.json')or{}
            start=timestamp(started.get('started_at'))or timestamp(started.get('at'))
        end=timestamp((result or{}).get('finished_at')) or timestamp((result or{}).get('finished_at_unix'))
        return start is not None and ((end is None or end>=self.cutoff)and start<=time.time())

    def observe(self,slot):
        candidates=[];new_runs=[];reserved_runs=[];inflight=False;new_terminal=None
        old=slot.get('selected_completed')
        if old:
            r=self.result(old['result_path'],slot,baseline=True,expected_sha=old['result_sha256'])
            if r:candidates.append(r)
        elif slot.get('latest_known_result'):
            old=slot['latest_known_result'];r=self.result(old['path'],slot,baseline=True,expected_sha=old['sha256'])
            if r:candidates.append(r)
        new=self.new.get(slot['slot_id'])
        if new:
            rp=Path(new['prediction_result_path']);attempt=rp.parent
            new_runs=[str(p)for p in(attempt/'runs').glob('attempt_*')if p.is_dir()]
            r=self.result(rp,slot)
            if r:candidates.append(r);new_terminal=r
            else:inflight=bool(new_runs)
        for record in slot.get('reservation_evidence',[]):
            attempt=Path(record['attempt_path']);r=self.result(attempt/'result.json',slot)
            if r:candidates.append(r)
            else:inflight=True
            for run in(attempt/'runs').glob('attempt_*'):
                if self.run_intersects(run):reserved_runs.append(str(run))
        chosen=choose_completed(candidates);score=None;gp=None;gh=None
        latest=max(candidates,key=lambda r:r.get('finished_unix') or 0) if candidates else None
        if chosen:
            score,gp,gh=self.grade(chosen,slot);status='completed_scored'if score is not None else'completed_ungraded';taskscore=score
        elif inflight:status='active';taskscore=None
        else:
            latest=max(candidates,key=lambda r:r.get('finished_unix')or 0)if candidates else None
            if latest and not latest['identity_valid']:status='identity_quarantined'
            elif latest and latest['status']=='failed'and latest['failure_category']in BUDGET and latest['cleanup_confirmed']:status='task_budget_failed'
            elif latest and latest['status']=='timeout':status='timeout_unresolved'
            elif latest and latest['status']=='failed':status='system_or_unclassified_failed'
            elif latest and latest['status']=='not_started':status='not_started'
            elif new:status='pending_new_pass'
            else:status='missing_or_other'
            taskscore=0. if status=='task_budget_failed'else None
        # Pending authorization remains pending even when an old attempt timed out.
        if new and not new_runs and new_terminal is None and chosen is None:status='pending_new_pass';taskscore=None
        result={'slot_id':slot['slot_id'],'benchmark':slot['benchmark'],'harness':slot['harness'],'method':slot['method'],
                'question_id':slot['question_id'],'repeat':slot['repeat'],'status':status,'score':score,'task_valid_score':taskscore,
                'selected_result_path':chosen['result_path']if chosen else None,'selected_result_sha256':chosen['result_sha256']if chosen else None,
                'grade_path':gp,'grade_sha256':gh,'new_pass_end_to_end_seconds':new_terminal['end_to_end_seconds']if new_terminal else None,
                'latest_terminal_result_path':latest['result_path'] if latest else None,
                'latest_terminal_result_sha256':latest['result_sha256'] if latest else None,
                'latest_terminal_status':latest['status'] if latest else None,
                'latest_failure_category':latest['failure_category'] if latest else None,
                **replay_flags(new_runs,reserved_runs)}
        return result

    def safe_observe(self,slot):
        try:
            return self.observe(slot)
        except Exception as exc:
            self.errors.append({'slot_id':slot['slot_id'],'error_type':type(exc).__name__})
            return {k:slot[k] for k in ('slot_id','benchmark','harness','method','question_id','repeat')} | {
                'status':'read_quarantined','score':None,'task_valid_score':None,
                'selected_result_path':None,'selected_result_sha256':None,'grade_path':None,'grade_sha256':None,
                'new_pass_end_to_end_seconds':None,**replay_flags([],[])}

    def resources(self,groups):
        p=Path(self.mapping['grading_root'])/'resources.json';value=self.read(p)
        result={'path':str(p),'available':value is not None,'scope':'V15 new predictions only; historical attempts and judge costs are not silently included or reset.',
                'historical_ledger_source':self.bound_sources['baseline'],'usd':None,'provider_internal_api_latency_seconds':None}
        if not value:return result
        result.update(at=value.get('at'),source_sha256=self.hashes[str(p)])
        bycell={j['cell']:self.slots[j['slot_id']]for j in self.new.values()}
        for cell,data in value.get('cells',{}).items():
            if cell not in bycell:continue
            slot=bycell[cell];g=groups[(slot['benchmark'],slot['harness'],slot['method'])]
            costs=g.setdefault('new_pass_tokens',{'scope':'new V15 HTTP attempts only','cells_observed':0,'unknown_usage_attempts':0,'fields':{}})
            costs['cells_observed']+=1;costs['unknown_usage_attempts']+=data.get('unknown_usage_attempts',0)
            for name in('cached_input','noncache_input','output','total'):
                source=data.get('new_prediction_all_attempts',{}).get('fields',{}).get(name)
                if source is None:continue
                target=costs['fields'].setdefault(name,{'known_subtotal':0,'missing_count':0,'complete_total':0})
                target['known_subtotal']+=source.get('known_subtotal',0);target['missing_count']+=source.get('missing_count',0)
                if target['complete_total']is None or source.get('complete_total')is None:target['complete_total']=None
                else:target['complete_total']+=source['complete_total']
        for key,g in groups.items():
            expected_cells={cell for cell,slot in bycell.items() if (slot['benchmark'],slot['harness'],slot['method'])==key}
            if not expected_cells:continue
            costs=g.setdefault('new_pass_tokens',{'scope':'new V15 HTTP attempts only','cells_observed':0,'unknown_usage_attempts':None,'fields':{}})
            costs['cells_expected']=len(expected_cells)
            costs['missing_cells']=sorted(expected_cells-set(value.get('cells',{})))
            if costs['missing_cells']:
                for field in costs['fields'].values():field['complete_total']=None
        return result

    def snapshot(self,final=False):
        started=time.time();self.errors=[]
        with ThreadPoolExecutor(max_workers=self.workers)as executor:rows=list(executor.map(self.safe_observe,self.base['slots']))
        groups={}
        for key in sorted({(r['benchmark'],r['harness'],r['method'])for r in rows}):
            rr=[r for r in rows if(r['benchmark'],r['harness'],r['method'])==key]
            e2e=[r['new_pass_end_to_end_seconds']for r in rr if isinstance(r['new_pass_end_to_end_seconds'],(int,float))]
            groups[key]={'benchmark':key[0],'harness':key[1],'method':key[2],'slots':300,'states':dict(Counter(r['status']for r in rr)),
                         'completed_only':repeat_statistics(rr),'task_valid':repeat_statistics(rr,'task_valid_score'),
                         'coverage_completed':sum(r['status'].startswith('completed_')for r in rr)/300,
                         'failure_categories':dict(Counter(r.get('latest_failure_category') or 'unclassified' for r in rr if r['status'] in ('task_budget_failed','system_or_unclassified_failed','timeout_unresolved'))),
                         'new_pass_end_to_end_seconds_mean_terminal':statistics.mean(e2e)if e2e else None,
                         'new_pass_end_to_end_terminal_n':len(e2e),'client_api_seconds':None,'render_seconds':None,'usd':None,
                         'replay_slots':[r['slot_id']for r in rr if r['replay_detected']]}
        resource=self.resources(groups)
        result={'version':'once24h-fixed-cohort-report-v1','at':datetime.now(timezone.utc).isoformat(),'final':final,'deadline_utc':'2026-11-14T19:20:06Z',
                'model_calls':0,'scope_slots':6900,'baseline':self.bound_sources,'totals':dict(Counter(r['status']for r in rows)),
                'replay_detected_slots':[r['slot_id']for r in rows if r['replay_detected']],
                'groups':list(groups.values()),'resource_reference':resource,'observations':rows,'read_errors':self.errors,
                'interpretation':['Keep earliest legal completed by execution time, never by correctness; RQ3 uses only the seven-page V10+ protocol.',
                'Main mean and sample std use three repeat accuracies among completed, SHA-matched scored results; unequal/incomplete denominators are shown.',
                'task_valid additionally counts only explicit clean task-budget failures as zero; system failures and unresolved timeouts are never zero-filled.',
                'Token subtotals cover only new V15 prediction attempts and may be incomplete; missing usage, prices, provider latency, and unaggregated rendering remain NA.',
                'End-to-end means include all observed new terminal attempts; they are not provider API latency.',
                'Active is inferred from started attempt directories with no terminal outer result; this is not a fresh OS liveness assertion.'],
                'snapshot_client_seconds':time.time()-started}
        atomic(self.output/'latest.json',result);atomic(self.output/'latest.md',render_markdown(result))
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        atomic(self.output/'history'/f'{stamp}.json',{k:v for k,v in result.items()if k!='observations'})
        if final:atomic(self.output/'final.json',result);atomic(self.output/'final.md',render_markdown(result))
        return result


def render_markdown(result):
    lines=['# 单次补跑进度','',f"更新时间：{result['at']}；截止：{result['deadline_utc']}。",'',
           '保留最早合法完成结果，不按正确性择优。RQ3仅使用七页V10及后继协议。均值±标准差来自三个repeat已有评分的完成题次；分母不足300时不是完整avg@3。','',
           '|Benchmark|Harness|方法|完成/300|已评分|每repeat分母|mean ± std (%)|在途|待跑|超时|其他失败|',
           '|---|---|---|---:|---:|---|---:|---:|---:|---:|---:|']
    for g in result['groups']:
        s=g['states'];stats=g['completed_only'];value='NA'if stats['mean']is None else f"{stats['mean']*100:.2f} ± {stats['sample_std']*100:.2f}"
        completed=s.get('completed_scored',0)+s.get('completed_ungraded',0);other=sum(s.get(k,0)for k in('system_or_unclassified_failed','task_budget_failed','identity_quarantined','read_quarantined','missing_or_other'))
        lines.append(f"|{g['benchmark']}|{g['harness']}|{g['method']}|{completed}|{stats['valid_n']}|"+'/'.join(str(r['valid_n'])for r in stats['repeats'])+f"|{value}|{s.get('active',0)}|{s.get('pending_new_pass',0)}|{s.get('timeout_unresolved',0)}|{other}|")
    lines+=['','仅明确任务预算耗尽的附加零分统计保存在JSON的task_valid；系统失败和未知原因超时不补0。','',
            f"重复执行告警：{len(result['replay_detected_slots'])}槽。读取异常：{len(result['read_errors'])}条。",'',
            '新轮成本与延迟仅引用现有聚合：历史成本保留在原账本，未在此表重复累加。NA表示未测量或无法确认，不等于0。','',
            '|Benchmark/Harness/方法|cached input|non-cache input|output|total|未知usage请求|E2E均值(秒，已终态)|API客户端秒|渲染秒|USD|',
            '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in result['groups']:
        costs=g.get('new_pass_tokens',{});fields=costs.get('fields',{});vals=[]
        for k in('cached_input','noncache_input','output','total'):
            f=fields.get(k);vals.append('NA'if not f else str(f['complete_total'])if f['complete_total']is not None else f"≥{f['known_subtotal']}（不完整）")
        e2e=g['new_pass_end_to_end_seconds_mean_terminal'];lines.append('|'+g['benchmark']+'/'+g['harness']+'/'+g['method']+'|'+'|'.join(vals)+'|'+str(costs.get('unknown_usage_attempts','NA'))+'|'+('NA'if e2e is None else f'{e2e:.1f}')+'|NA|NA|NA|')
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--baseline',type=Path,default=DEFAULT_BASE);parser.add_argument('--grading-map',type=Path,default=DEFAULT_MAP);parser.add_argument('--output',type=Path,default=DEFAULT_OUT);parser.add_argument('--workers',type=int,default=8);parser.add_argument('--watch',action='store_true');parser.add_argument('--interval',type=int,default=900);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);lock=open(args.output/'controller.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    atomic(args.output/'observer-start.json',{'pid':os.getpid(),'at_unix':time.time(),'source_sha256':digest(Path(__file__).read_bytes()),'model_calls':0,'interval_seconds':args.interval})
    reporter=Reporter(args.baseline,args.grading_map,args.output,args.workers)
    while True:
        final=time.time()>=DEADLINE;result=reporter.snapshot(final);print(json.dumps({'at':result['at'],'final':final,'totals':result['totals'],'replays':len(result['replay_detected_slots'])}),flush=True)
        if final or not args.watch or(args.output/'STOP').exists():break
        time.sleep(max(1,min(args.interval,DEADLINE-time.time())))


if __name__=='__main__':main()
