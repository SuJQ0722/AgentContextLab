"""Zero-call BC snapshot: preserve completed predictions; compare strict paired repeats."""
import argparse
import collections
import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from analyze_bc_completed_intersection_v2 import METHODS, summary

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT/'outputs/grading/bc100-v3-deepseek-sfb-v1/analysis'
CAMPAIGNS = ('visual-hosted-failure-retry-v1', 'visual-hosted-transport-v4',
    'visual-inline-failure-retry-v5', 'dsh-cli-separator-v1', 'visual-inline-canary-v6',
    'visual-inline-two-hour-v7')
RECOVERY = {'visual-inline-failure-retry-v5':'visual-inline-judge-recovery-v1',
            'visual-inline-two-hour-v7':'visual-inline-two-hour-judge-recovery-v1'}

class Snapshot:
    def __init__(self): self.sources = {}; self.cache = {}
    def read(self, path):
        path = Path(path).resolve()
        if path not in self.cache:
            raw = path.read_bytes(); self.sources[str(path.relative_to(ROOT))] = hashlib.sha256(raw).hexdigest()
            self.cache[path] = ([json.loads(x) for x in raw.decode().splitlines() if x.strip()]
                                if path.suffix == '.jsonl' else json.loads(raw))
        return self.cache[path]
    def sha(self, path):
        self.read(path); return self.sources[str(Path(path).resolve().relative_to(ROOT))]


def require(ok, message):
    if not ok: raise ValueError(message)


def select(prior, candidate):
    # Selection is independent of scores, cleanup checks, and later correctness.
    return prior if prior['prediction_status'] == 'completed' else candidate


def clean(result):
    return (result['status'] == 'completed' and not result.get('failure_category')
        and not result.get('error_type') and result.get('exit_code') in (0, None)
        and result.get('slot_released') is not False and not result.get('unconfirmed_child_termination'))


def question_hash(question): return hashlib.sha256(question.encode()).hexdigest()


def check_result(snap, row):
    path = Path(row['attempt'])/'result.json'; result = snap.read(path)
    require(result['job_id'] == row['job_id'], 'Result job mismatch')
    for field in ('question_id', 'repeat', 'harness'):
        require(result.get(field) == row[field], 'Result identity mismatch: '+field)
    row.update(result_path=str(path), result_sha256=snap.sha(path),
               prediction_status=result['status'], failure_category=result.get('failure_category'),
               clean_completed=clean(result), cleanup_unconfirmed=(result.get('slot_released') is False or bool(result.get('unconfirmed_child_termination'))))
    return row


def check_grade(snap, row):
    row['score'] = None; row['score_reason'] = 'missing_bound_grade'
    if row['prediction_status'] != 'completed' or not row.get('judge_path'): return
    path = Path(row['judge_path'])
    if not path.exists(): return
    grade = snap.read(path); row['score_reason'] = 'bound_grade_not_scored'
    for key, value in [('job_id', row['job_id']), ('result_sha256', row['result_sha256']),
                       ('question_sha256', row['question_hash'])]:
        require(grade.get(key) == value, 'Grade binding mismatch '+str(path)+' '+key)
    if 'plan_sha256' in grade:
        require(grade['plan_sha256'] == snap.sha(row['plan_path']), 'Grade plan SHA mismatch')
    if 'result_path' in grade:
        require(Path(grade['result_path']).resolve() == Path(row['result_path']).resolve(), 'Grade result path mismatch')
    for field in ('question_id','repeat','harness'):
        if field in grade: require(grade[field] == row[field], 'Grade identity mismatch '+field)
    if grade.get('status') == 'scored' and type(grade.get('score')) in (int,float) and grade['score'] in (0,1):
        row.update(score=grade['score'], grade_sha256=snap.sha(path), judge_model=grade.get('judge_model'),
                   score_reason='bound_scored_completed')


def recovery_grade(snap, campaign, cell, jid, original):
    if campaign not in RECOVERY: return original
    resolved = ROOT/'outputs/grading'/RECOVERY[campaign]/'cells'/cell/'jobs'/jid/'resolved.json'
    if not resolved.exists(): return original
    value = snap.read(resolved)
    require(value['job_id'] == jid and value['cell'] == cell, 'Recovery identity mismatch')
    require(Path(value['old_grade_path']) == original, 'Recovery original path mismatch')
    require(snap.sha(original) == value['old_grade_sha256'], 'Recovery old grade SHA mismatch')
    require(snap.read(original).get('status') != 'scored', 'Successful original grade replaced')
    path = Path(value['grade_path']); grade = snap.read(path)
    require(grade.get('status') == 'scored' and grade.get('score') == value['score'], 'Recovery grade mismatch')
    return path


def paired_scope(index):
    common = set.intersection(*(set(rows) for rows in index.values()))
    for key in common:
        hashes = {rows[key]['question_hash'] for rows in index.values() if 'question_hash' in rows[key]}
        require(len(hashes) <= 1, 'Paired question hash mismatch')
    completed = {k for k in common if all(rows[k]['clean_completed'] for rows in index.values())}
    scored = {k for k in completed if all(rows[k]['score'] in (0,1) for rows in index.values())}
    return {'completed_slots':len(completed), 'missing_any_grade_slots':len(completed-scored), **summary(index,scored)}


def build():
    scan_started = datetime.now(timezone.utc).isoformat()
    snap = Snapshot(); rows = {}; audit = []; pending = {}
    first = {r['job_id']:r for r in snap.read(BASE/'first-pass-observations.jsonl')}
    for source in snap.read(BASE/'selected-observations.jsonl'):
        row = dict(source); jid = row['job_id']
        require(jid not in rows, 'Duplicate baseline slot')
        require(row['selection'] in ('retained_original_completed','fixed_retry_regardless_of_outcome'), 'Unapproved baseline selection')
        if row['selection'] == 'fixed_retry_regardless_of_outcome':
            require(first[jid]['prediction_status'] != 'completed', 'Baseline discarded completed result')
        campaign = Path(row['attempt']).relative_to(ROOT/'outputs/campaigns').parts[0]
        require(campaign in ('bc100-r3-hermes-parity-v3','bc100-r3-hermes-parity-v3-retry1'), 'Unapproved baseline campaign')
        pp = ROOT/'outputs/campaigns'/campaign/'plan.json'; plan = snap.read(pp)
        job = next(j for j in plan['jobs'] if j['job_id'] == jid)
        require(question_hash(job['question']) == row['question_hash'], 'Baseline question mismatch')
        row.update(plan_path=str(pp), selected_campaign=campaign)
        rows[jid] = check_result(snap,row)
    require(len(rows) == 3000, 'Expected exactly 3000 baseline slots')
    for campaign in CAMPAIGNS:
        grading = ROOT/'outputs/grading'/campaign
        for cell in ('bc_hermes','bc_dsh'):
            bp = grading/'cells'/cell/'source-binding.json'
            if not bp.exists(): continue
            binding = snap.read(bp); root = Path(binding['root']); pp = root/'plan.json'; plan = snap.read(pp)
            require(snap.sha(pp) == binding['plan_sha256'], 'Grading plan SHA mismatch')
            require(plan['definition'].get('selection_uses_answers') is False, 'Answer-selected overlay prohibited')
            config = root/'experiment.json'
            require(snap.sha(config) == binding['config_sha256'], 'Config SHA mismatch')
            for job in plan['jobs']:
                jid = job['job_id']; old = rows[jid]
                require(question_hash(job['question']) == old['question_hash'], 'Overlay question mismatch')
                require(job['question_id'] == old['question_id'] and job['repeat'] == old['repeat'], 'Overlay identity mismatch')
                attempt = root/'jobs'/jid/'attempts/attempt_001'; rp = attempt/'result.json'
                if old['prediction_status'] == 'completed':
                    audit.append({'campaign':campaign,'job_id':jid,'decision':'retain_any_completed_without_score_selection'})
                    pending.pop(jid,None); continue
                if not rp.exists():
                    if campaign == CAMPAIGNS[-1]:
                        started = attempt/'worker-started.json'; heartbeat = attempt/'heartbeat.json'
                        state = 'recovery_pending'
                        if started.exists():
                            snap.read(started); state = 'recovery_running_unverified'
                            if heartbeat.exists():
                                hb = snap.read(heartbeat)
                                if not hb.get('finished') and datetime.now(timezone.utc).timestamp()-hb.get('heartbeat_unix',0)<180:
                                    state = 'recovery_running'
                        pending[jid] = {'state':state,'campaign':campaign,'attempt':str(attempt)}
                    continue
                result = snap.read(rp)
                require(result['status'] in ('completed','failed','timeout','interrupted','not_started'), 'Unknown terminal status')
                gp = grading/'cells'/cell/'jobs'/jid/'grade.json'
                gp = recovery_grade(snap,campaign,cell,jid,gp)
                candidate = {**old,'attempt':str(attempt),'judge_path':str(gp),'plan_path':str(pp),
                    'selected_campaign':campaign,'prediction_status':result['status'],'selection':'execution_only_preserve_any_completed'}
                check_result(snap,candidate)
                rows[jid] = select(old,candidate); pending.pop(jid,None)
                audit.append({'campaign':campaign,'job_id':jid,'decision':'latest_terminal_after_noncompleted',
                              'result_path':str(rp),'result_sha256':snap.sha(rp)})
    for row in rows.values():
        check_grade(snap,row)
        row['effective_status'] = pending.get(row['job_id'],{}).get('state',row['prediction_status'])
        row['current_recovery'] = pending.get(row['job_id'])
    scopes = {}; statuses = {}; cross = {}
    for harness in ('hermes','dsh'):
        index = {method:{(r['question_id'],r['repeat']):r for r in rows.values()
                         if r['harness']==harness and r['method']==method} for method in METHODS}
        require(all(len(v)==300 for v in index.values()), 'Expected 300 slots per method')
        scopes[harness] = paired_scope(index)
        for method, values in index.items():
            name = harness+'/'+method; cross[name] = values
            count = collections.Counter(r['effective_status'] for r in values.values())
            statuses[name] = {k:count[k] for k in ('completed','timeout','failed','interrupted','not_started','recovery_running','recovery_pending','recovery_running_unverified')}
            statuses[name].update(total=sum(count.values()),cleanup_unconfirmed=sum(r['cleanup_unconfirmed'] for r in values.values()),completed_scored=sum(r['clean_completed'] and r['score'] in (0,1) for r in values.values()))
    scopes['cross_harness_all10'] = paired_scope(cross)
    report = {'version':'bc-completion-intersection-v3','at':datetime.now(timezone.utc).isoformat(),
        'snapshot_started_at':scan_started,'snapshot_semantics':'Each file read once and SHA recorded; live files sampled during stated scan interval, not an atomic filesystem snapshot.',
        'paid_calls':0,'model_calls':0,'read_only_live_campaigns':True,'excluded_prediction_campaigns':['bc-bounded-retry-v1'],
        'overlay_order':list(CAMPAIGNS),'selection_rule':'Retain any prior completed prediction including incorrect answers. Otherwise select latest terminal execution-only recovery. Current recovery running/pending replaces status display only, never duplicates its predecessor slot.',
        'interpretation':'Conditional common completed-and-scored subset, not full-cohort accuracy. Strict avg3 uses only questions with all 3 repeats scored for every compared method. Std is sample standard deviation across three repeat accuracies (ddof=1).',
        'dataset_modality':'text BC100; visual refers to context representation, not question modality',
        'modalities':{'none':'text','discard':'text','summarize':'text','sliding_window':'text','visual':'visual'},
        'scopes':scopes,'status_by_method':statuses,'selected_campaign_counts':dict(collections.Counter(r['selected_campaign'] for r in rows.values())),
        'source_sha256':snap.sources,'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return report,list(rows.values()),audit


def markdown(report):
    lines=['# BC DeepSeek：共同完成且已评分子集', '', '快照时间：'+report['at'], '',
        '数据集：文本 BC100；visual 指上下文表达方式。',
        '保留任何历史 completed（包括答错）；仅执行失败可由后继终态替代。排除按答案挑选的 bounded retry。零模型调用。',
        'avg3 ± std 仅使用所有比较方法、全部三个重复均完成且评分的问题；std 为三次准确率的样本标准差，单位为百分点。此为条件子集准确率，不代表完整100题。', '']
    for scope, value in report['scopes'].items():
        lines += ['## '+scope, '', f"共同已完成槽 {value['completed_slots']}；共同完成且已评分槽 {value['slots']}；缺任一评分排除 {value['missing_any_grade_slots']} 槽；严格三重复问题 {len(value['balanced_questions'])}。", '', '| 方法 | 三次正确数 / 每次题数 | avg3 ± std |', '|---|---|---|']
        for method,data in value['methods'].items():
            b=data['balanced_avg3']; rate='缺数据' if b['mean'] is None else f"{100*b['mean']:.2f} ± {100*b['sample_std_ddof1']:.2f}%"
            lines.append(f"| {method} | {b['per_repeat_correct']} / {b['questions']} | {rate} |")
        lines.append('')
    lines += ['## 每方法300槽当前状态', '', '| Harness/方法 | completed | timeout | failed | interrupted/not_started | recovery运行 | recovery待运行 | recovery状态未核实 | completed且已评分 |', '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,s in report['status_by_method'].items():
        lines.append(f"| {name} | {s['completed']} | {s['timeout']} | {s['failed']} | {s['interrupted']+s['not_started']} | {s['recovery_running']} | {s['recovery_pending']} | {s['recovery_running_unverified']} | {s['completed_scored']} |")
    lines += ['', '清理状态未确认（是上述状态的附加标记，不另计槽）：'+json.dumps({k:s['cleanup_unconfirmed'] for k,s in report['status_by_method'].items() if s['cleanup_unconfirmed']},ensure_ascii=False)]
    return '\n'.join(lines)+'\n'


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    require(not a.output.exists(), 'Use a new output directory; never overwrite a previous snapshot')
    report,rows,audit=build();a.output.mkdir(parents=True)
    for name,value in [('report.json',report),('overlay-decisions.json',audit)]:
        (a.output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    (a.output/'selected-observations.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (a.output/'report.md').write_text(markdown(report))
    print(json.dumps({'output':str(a.output),'balanced_questions':{k:len(v['balanced_questions']) for k,v in report['scopes'].items()},'statuses':report['status_by_method']},ensure_ascii=False))

if __name__=='__main__':main()
