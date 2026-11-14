"""Read-only fixed180 source-cohort comparison, separating reuse from interventions."""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import time
from datetime import datetime,timezone
from lab import ROOT
from controlled_mmbc_source_v20 import DEFAULT,DEADLINE,read,sha,save
from report_once24h_v15 import repeat_statistics
OUT=ROOT/'outputs/reports/controlled-source-v20'
GRADING=ROOT/'outputs/grading/controlled-mmbc-vera-nontimeout-v20/report.json'
SUMMARY23=ROOT/'outputs/controlled-mmbc-vera-nontimeout-summary-v23'
GRADING23=ROOT/'outputs/grading/controlled-mmbc-vera-nontimeout-summary-v23/report.json'
SUMMARY22=ROOT/'outputs/controlled-mmbc-vera-nontimeout-summary-v22'
GRADING22=ROOT/'outputs/grading/controlled-mmbc-vera-nontimeout-summary-v22/report.json'
SOURCE=ROOT/'outputs/controlled-mmbc-vera-nontimeout-v17/source-report-core-corrected.json'


def render(value):
    lines=['# MMBC受控baseline：冻结180题次','',f"更新时间：{value['at']}。在原300题次中选择VERA未超时的180题次；新增VERA补跑不会扩大集合。",'',
      '每臂109题次需要实际干预续跑，67题次原轨迹无压缩、直接复用同一结果，4题次被阻塞（2题次缺少实测目标token，2题次原生图像为11张、超过10张上限）。本文本续跑比较不声称为全新100×3实验。','',
      '|方法|新续跑完成|新续跑已评分|共享无干预复用|超时|预算不可匹配|模型前失败|其他失败|阻塞|在跑/待跑|有效分母(repeat)|有效结果mean ± std (%)|',
      '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|']
    for method in value['methods']:
        states=method['states'];stats=method['effective_available'];rate='NA'if stats['mean']is None else f"{100*stats['mean']:.2f} ± {100*stats['sample_std']:.2f}"
        lines.append(f"|{method['method']}|{states.get('completed',0)}|{method['new_intervention_scored']['valid_n']}|{states.get('no_compression_reuse',0)}|{states.get('timeout',0)}|{method['failure_categories'].get('budget_infeasible',0)}|{method['failure_categories'].get('pre_model_system_failed',0)}|{method['failure_categories'].get('other_failed',0)}|{states.get('blocked',0)}|{states.get('pending',0)}|"+'/'.join(str(x['valid_n'])for x in stats['repeats'])+f"|{rate}|")
    lines+=['',f"终态直接读取当前terminal；评分观察时间另列：{value['grading_observed_at_by_protocol']}。报告生成时间不代表评分同步完成。",'','上表有效结果包含明确标记的共享无干预复用；系统失败、blocked和未知分数不补0。新续跑单独mean±std、三个方法共同完成的干预子集、每题来源及预算证据见JSON。',f"严格三方法新干预配对：{value['paired_intervention_slots']}题次。所有历史原始成绩和成本均保留。"]
    lines+=['','摘要协议分层（v20已付费25、v22正式canary1均不重跑；v23只接管剩余83）：','', '|版本|题次|状态|','|---|---:|---|']
    for row in value['summary_protocols']:lines.append(f"|{row['protocol']}|{row['slots']}|{json.dumps(row['states'],ensure_ascii=False)}|")
    return '\n'.join(lines)+'\n'


def snapshot():
    plan=read(DEFAULT/'plan.json');cohort=read(plan['cohort_path']);source=read(SOURCE)
    baseline={(r['question_id'],r['repeat']):r for r in source['observations']if(r['benchmark'],r['harness'],r['method'])==('mmbc100','hermes','visual')}
    report=read(GRADING)if GRADING.exists()else{'rows':[]};grades={r['job_id']:r for r in report['rows']};rows=[]
    plan22=read(SUMMARY22/'plan.json')if(SUMMARY22/'plan.json').exists()else{'jobs':[]}
    newjobs={j['job_id']:j for j in plan22['jobs']}
    report22=read(GRADING22)if GRADING22.exists()else{'rows':[]}
    grades22={r['job_id']:r for r in report22['rows']}
    plan23=read(SUMMARY23/'plan.json')if(SUMMARY23/'plan.json').exists()else{'jobs':[]}
    newjobs23={j['job_id']:j for j in plan23['jobs']}
    report23=read(GRADING23)if GRADING23.exists()else{'rows':[]}
    grades23={r['job_id']:r for r in report23['rows']}
    for job in plan['jobs']:
        src=baseline[(job['question_id'],job['repeat'])]
        if job['source_result_sha256']not in(src.get('selected_result_sha256'),src.get('latest_terminal_result_sha256')):raise ValueError('Fixed source differs from corrected core observation')
        effective_job=newjobs23.get(job['job_id'],newjobs.get(job['job_id'],job))
        if effective_job['source_result_sha256']!=job['source_result_sha256']:raise ValueError('New summary changed frozen source')
        protocol='summary-v23'if job['job_id']in newjobs23 else'summary-v22'if job['job_id']in newjobs else'controlled-v20'
        actual=(grades23 if job['job_id']in newjobs23 else grades22 if job['job_id']in newjobs else grades).get(job['job_id'],{})
        grading_observed_at=(report23 if job['job_id']in newjobs23 else report22 if job['job_id']in newjobs else report).get('at')
        terminal_path=Path(effective_job['output_path'])/'terminal.json';terminal=read(terminal_path)if terminal_path.exists()else{}
        if terminal and terminal.get('job_id')!=job['job_id']:raise ValueError('Terminal identity mismatch')
        status=terminal.get('status','pending');score=actual.get('score');failure_category=None
        if status=='failed':
            attempt=Path(effective_job['output_path']);result=read(attempt/'result.json')if(attempt/'result.json').exists()else{}
            failure_category='budget_infeasible' if result.get('status')=='budget_infeasible' else 'pre_model_system_failed' if not(attempt/'metrics/call-starts.jsonl').exists()else'other_failed'
        origin='new_intervention' if score in(0,1)else None
        vera_score=src.get('score')if src['status']=='completed_scored'else None
        if job['action']=='no_compression_reuse':score=vera_score;origin='shared_no_intervention'if score in(0,1)else None
        rows.append({'job_id':job['job_id'],'question_id':job['question_id'],'repeat':job['repeat'],'method':job['method'],
            'action':job['action'],'grading_observed_at':grading_observed_at,'terminal_observed_at':time.time(),'prediction_protocol':protocol,'status':status,'failure_category':failure_category,'score':score,'score_origin':origin,'vera_score':vera_score,
            'source_result_sha256':job['source_result_sha256'],'control_valid':actual.get('control_valid'),
            'actual_prompt_tokens':actual.get('actual_prompt_tokens'),'source_prompt_tokens':actual.get('source_prompt_tokens'),
            'grade_path':actual.get('grade_path'),'prediction_accounting_path':actual.get('prediction_accounting_path')})
    protocols=[]
    for name in ('controlled-v20','summary-v22','summary-v23'):
        rr=[r for r in rows if r['method']=='summary' and r['action']=='matched_continuation' and r['prediction_protocol']==name]
        protocols.append({'protocol':name,'slots':len(rr),'states':dict(Counter(r['status']for r in rr)),'scored':repeat_statistics(rr),'failure_categories':dict(Counter(r['failure_category']for r in rr if r['failure_category']))})
    methods=[]
    for name in('summary','window'):
        rr=[r for r in rows if r['method']==name]
        methods.append({'method':name,'states':dict(Counter(r['status']for r in rr)),'failure_categories':dict(Counter(r['failure_category']for r in rr if r['failure_category'])),
            'effective_available':repeat_statistics(rr),'new_intervention_scored':repeat_statistics([r for r in rr if r['score_origin']=='new_intervention']),
            'timeout_fraction_of_full_300':sum(r['status']=='timeout'for r in rr)/300,
            'timeout_fraction_of_selected_180':sum(r['status']=='timeout'for r in rr)/180})
    grouped={}
    for r in rows:grouped.setdefault((r['question_id'],r['repeat']),{})[r['method']]=r
    paired=[g for g in grouped.values()if set(g)=={'summary','window'}and all(r['score_origin']=='new_intervention'and r['control_valid']and r['vera_score']in(0,1)for r in g.values())]
    paired_stats={m:repeat_statistics([{'repeat':g['summary']['repeat'],'score':g['summary']['vera_score']if m=='vera'else g[m]['score']}for g in paired])for m in('vera','summary','window')}
    value={'version':'fixed-source-controlled-pairs-v20','at':datetime.now(timezone.utc).isoformat(),'plan_sha256':sha(DEFAULT/'plan.json'),
        'cohort_sha256':plan['cohort_sha256'],'source_report_sha256':sha(SOURCE),'grading_report_sha256':sha(GRADING)if GRADING.exists()else None,
        'cohort_slots':180,'full_benchmark_slots':300,'new_intervention_per_method':109,'no_intervention_shared_per_method':67,
        'blocked_per_method':4,'summary_protocols':protocols,'grading_observed_at_by_protocol':{'controlled-v20':report.get('at'),'summary-v22':report22.get('at'),'summary-v23':report23.get('at')},'terminal_states_from_live_files':True,'summary_v23_plan_sha256':sha(SUMMARY23/'plan.json')if(SUMMARY23/'plan.json').exists()else None,'summary_v22_plan_sha256':sha(SUMMARY22/'plan.json')if(SUMMARY22/'plan.json').exists()else None,'methods':methods,'rows':rows,'paired_intervention_slots':len(paired),'paired_intervention_statistics':paired_stats,
        'model_calls':0,'image_token_parity_claimed':False,'reuse_is_new_measurement':False,'source_prefix_single_intervention':True,'fixed_cohort_not_expanded_by_vera_recovery':True}
    save(OUT/'latest.json',value);(OUT/'latest.md').write_text(render(value));return value


def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    lock=(OUT/'report.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        snapshot()
        if not a.watch or time.time()>=DEADLINE:return
        time.sleep(60)

if __name__=='__main__':main()
