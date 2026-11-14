"""SHA-bound 300-slot core MMBC overlay; new timeout rounds are not new seeds.

Preserves the immutable historical and controlled-cohort files. Physical legacy
attempts remain visible, but controlled experiments never become core answers or
core cost. Missing usage or system outcomes are not imputed as zero.
"""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import time

from lab import ROOT
from report_once24h_v15 import Reporter, atomic, repeat_statistics, DEADLINE

SOURCE = ROOT/'outputs/controlled-mmbc-vera-nontimeout-v17/source-report-core-corrected.json'
OUT = ROOT/'outputs/reports/mmbc-timeout-overlay-v18'
ROUNDS = ('mmbc-timeout-once-v18', 'mmbc-timeout-scope-correction-v19')


def read(path): return json.loads(Path(path).read_text())
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cost_scope(record):
    """Use source plan identity; pathname alone never proves a core cost."""
    path = Path(record.get('result_path') or str(Path(record['attempt_path'])/'result.json'))
    root = path
    while not (root/'plan.json').exists():
        if root == root.parent: return 'unclassified', None
        root = root.parent
    plan = read(root/'plan.json')
    job_id = str(path).split('/jobs/', 1)[1].split('/attempts/', 1)[0] if '/jobs/' in str(path) else None
    jobs = [j for j in plan.get('jobs', []) if j.get('job_id') == job_id]
    if len(jobs) != 1: return 'unclassified', {'plan_path': str(root/'plan.json'), 'plan_sha256': sha(root/'plan.json')}
    job = jobs[0]
    proof = {'plan_path': str(root/'plan.json'), 'plan_sha256': sha(root/'plan.json'), 'job_id': job_id,
             'experiment_kind': job.get('experiment_kind'), 'benchmark': job.get('benchmark'),
             'strategy': job.get('strategy'), 'harness': job.get('harness')}
    if job.get('experiment_kind') == 'controlled': return 'controlled', proof
    # Older core MMBC plans have no benchmark field; their explicit bounded
    # benchmark or campaign cell supplies that identity, not the question text.
    benchmark = job.get('benchmark') or job.get('bounded_benchmark')
    core_cell = plan.get('definition', {}).get('cell')
    is_mmbc = (benchmark in ('mmbc100', 'mmbrowsecomp') or core_cell in ('mmbc_vera', 'mmbc_visual')
               or plan.get('definition', {}).get('execution_version') in ('mmbc100-hermes-deepseek-v1','mmbc-vera-bounded-retry-v1'))
    if job.get('harness') == 'hermes' and job.get('strategy') == 'visual' and is_mmbc:
        return 'core_vera', proof
    return 'other_or_unclassified', proof


class Overlay(Reporter):
    def __init__(self, output=OUT):
        self.output = Path(output); self.workers = 4; self.immutable = {}; self.hashes = {}; self.errors = []
        source = self.read(SOURCE, stable=True)
        observed = [r for r in source['observations'] if (r['benchmark'],r['harness'],r['method']) == ('mmbc100','hermes','visual')]
        if len(observed) != 300 or len({r['slot_id'] for r in observed}) != 300: raise ValueError('Expected exactly 300 core slots')
        self.cutoff = datetime.fromisoformat('2026-11-14T03:25:12+00:00').timestamp()
        self.new = {}; self.plan_cache = {}; self.grade_paths = defaultdict(set); self.result_grade_paths = defaultdict(set); self.grade_bindings = defaultdict(list)
        slots = []
        for row in observed:
            slot = {k:row[k] for k in ('slot_id','benchmark','harness','method','question_id','question_sha256','repeat')}
            slot.update(selected_completed=None, latest_known_result=None, reservation_evidence=[])
            if row.get('selected_result_path'):
                slot['selected_completed'] = {'result_path':row['selected_result_path'], 'result_sha256':row['selected_result_sha256']}
                if row.get('grade_path'): self.grade_paths[row['selected_result_sha256']].add(row['grade_path'])
            elif row.get('latest_terminal_result_path'):
                slot['latest_known_result'] = {'path':row['latest_terminal_result_path'], 'sha256':row['latest_terminal_result_sha256']}
            slots.append(slot)
        self.base = {'slots':slots}; self.slots = {r['slot_id']:r for r in slots}
        self.source_states = dict(Counter(r['status'] for r in observed))
        self.bound_sources = {'core_corrected_report':str(SOURCE),'core_corrected_report_sha256':sha(SOURCE)}
        self.register_rounds()

    def register_rounds(self):
        for round_name in ROUNDS:
            prediction = ROOT/'outputs/campaigns'/round_name
            inventory = prediction/'inventory.json'
            if not inventory.exists(): continue
            for cell in self.read(inventory, stable=True)['cells']:
                root = Path(cell['root']); plan = self.read(root/'plan.json',stable=True)
                for job in plan['jobs']:
                    slot_id = job['slot_id']
                    result = root/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
                    grade = ROOT/'outputs/grading'/round_name/'cells'/cell['cell']/'jobs'/job['job_id']/'grade.json'
                    record = {'slot_id':slot_id,'prediction_result_path':str(result),'grade_path':str(grade),'round':round_name}
                    if slot_id in self.new and self.new[slot_id] != record: raise ValueError('Two new executions for one slot')
                    if slot_id not in self.slots or self.slots[slot_id]['selected_completed']: raise ValueError('New round contains a retained complete')
                    self.new[slot_id] = record
                    self.result_grade_paths[str(result)].add(str(grade))

    def ledger_partition(self):
        destination = self.output/'historical-cost-partition.json'
        existing = read(destination) if destination.exists() else None
        audits = [ROOT/'outputs/cloud-runtime'/r/'audit/eligible-timeout-once.json' for r in ROUNDS]
        bindings = {str(p):sha(p) for p in audits if p.exists()}
        if existing and existing['source_audit_sha256'] == bindings and existing.get('classifier_sha256') == sha(__file__): return existing
        seen = {}; rows = []
        for path in audits:
            if not path.exists(): continue
            for job in read(path)['jobs']:
                for record in job['cost_records']:
                    key = record['attempt_path']
                    if key in seen: continue
                    seen[key] = True
                    scope, proof = cost_scope(record)
                    rows.append({'slot_id':job['slot_id'], 'cost_scope':scope, 'classification_proof':proof,
                                 'original_cost_record':record, 'included_in_core_spend':scope=='core_vera'})
        result = {'version':'core-cost-partition-v18', 'classifier_sha256':sha(__file__), 'source_audit_sha256':bindings, 'rows':rows,
                  'physical_attempt_counts':dict(Counter(r['cost_scope'] for r in rows)),
                  'historical_token_totals':None, 'historical_usd':None,
                  'note':'Physical lineage retained without reset. This partition does not invent missing usage or add controlled costs to core VERA.'}
        atomic(destination,result); return result

    def snapshot(self, final=False):
        self.register_rounds(); self.errors=[]
        with ThreadPoolExecutor(max_workers=4) as pool: rows=list(pool.map(self.safe_observe,self.base['slots']))
        for row in rows:
            if row['slot_id'] in self.new: row['supplemental_round']=self.new[row['slot_id']]['round']
        states=dict(Counter(r['status'] for r in rows)); rounds=[]
        for name in ROUNDS:
            p=ROOT/'outputs/grading'/name/'resources.json'
            rounds.append({'round':name,'planned':sum(x['round']==name for x in self.new.values()),
                'states':dict(Counter(r['status'] for r in rows if r.get('supplemental_round')==name)),
                'new_prediction_resource_path':str(p),'new_prediction_resource_sha256':sha(p) if p.exists() else None,
                'resource_available':p.exists(),'resources':read(p) if p.exists() else None,
                'scope':'This new round only; historical attempts and judgments are separate.'})
        partition=self.ledger_partition()
        result={'version':'mmbc-core-timeout-overlay-v18','at':datetime.now(timezone.utc).isoformat(),'final':final,
            'scope_slots':300,'benchmark':'mmbc100','harness':'hermes','method':'visual','source':self.bound_sources,
            'frozen_source_states':self.source_states,'states':states,'completed_only':repeat_statistics(rows),
            'task_valid':repeat_statistics(rows,'task_valid_score'),'rounds':rounds,'observations':rows,
            'historical_cost_partition':{'path':str(self.output/'historical-cost-partition.json'),'sha256':sha(self.output/'historical-cost-partition.json'),'counts':partition['physical_attempt_counts']},
            'read_errors':self.errors,'model_calls':0,'baseline_cohort_unchanged':True,'new_seed':False,
            'notes':['Earliest legal core completion retained; no answer-based selection.',
                     'Task-valid counts only explicit clean task-budget exhaustion as zero; system failures and unresolved timeouts are missing.',
                     'Mean and sample std are over three repeat accuracies with shown available denominators; incomplete coverage is not full avg@3.',
                     'Historical controlled attempts retained in separate cost ledger, excluded from core answers and costs.']}
        atomic(self.output/'latest.json',result);atomic(self.output/'latest.md',markdown(result))
        if final:atomic(self.output/'final.json',result);atomic(self.output/'final.md',markdown(result))
        return result


def markdown(r):
    s=r['states']; stats=r['completed_only']; rate='NA' if stats['mean'] is None else f"{100*stats['mean']:.2f} ± {100*stats['sample_std']:.2f}"
    completed=s.get('completed_scored',0)+s.get('completed_ungraded',0)
    lines=['# MMBC VERA 核心实验回补结果','',f"更新时间：{r['at']}。原300题次；补跑不是新seed。",'',
        '|完成/300|已评分|三个repeat有效分母|mean ± std (%)|在跑|待跑|超时/300|其他失败|',
        '|---:|---:|---|---:|---:|---:|---:|---:|',
        f"|{completed}|{stats['valid_n']}|"+'/'.join(str(x['valid_n']) for x in stats['repeats'])+f"|{rate}|{s.get('active',0)}|{s.get('pending_new_pass',0)}|{s.get('timeout_unresolved',0)}|{sum(v for k,v in s.items() if k not in ('completed_scored','completed_ungraded','active','pending_new_pass','timeout_unresolved'))}|",'',
        '统计排除了误并入的受控实验轨迹。只保留最早合法核心完成；系统错误和未明确原因超时不补零。受控baseline集合固定，新增回补完成不会自动扩大集合。','',
        '|回补轮次|题次|状态|','|---|---:|---|']
    for x in r['rounds']:lines.append(f"|{x['round']}|{x['planned']}|{json.dumps(x['states'],ensure_ascii=False)}|")
    lines+=['','新轮token及延迟逐轮保存在JSON资源引用中；历史成本保留并按core VERA / controlled / other分账。未测得的成本、provider API延迟不视为0。',f"历史物理attempt归属：{r['historical_cost_partition']['counts']}。读取异常：{len(r['read_errors'])}。"]
    return '\n'.join(lines)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--watch',action='store_true');args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);lock=(OUT/'report.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    reporter=Overlay()
    while True:
        final=time.time()>=DEADLINE;value=reporter.snapshot(final)
        print(json.dumps({'at':value['at'],'states':value['states'],'errors':len(value['read_errors']),'final':final}),flush=True)
        if not args.watch or final:return
        time.sleep(60)

if __name__=='__main__':main()
