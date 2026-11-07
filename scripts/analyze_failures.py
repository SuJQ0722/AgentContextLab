#!/usr/bin/env python3
"""Offline, evidence-conservative failure audit. Makes no model calls."""
import collections
from concurrent.futures import ThreadPoolExecutor
import csv
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]
BINS=['0–10','11–30','31–60','61–100','101+','missing']

def bucket(n):
    if n is None:return 'missing'
    return BINS[next((i for i,b in enumerate([10,30,60,100]) if n<=b),4)]

def classify(d,h,score):
    # Search diagnostic fields, never retrieved pages or model-generated claims.
    diagnostic='\n'.join(str(h.get(k) or '') for k in ['error','error_code','stderr_tail','agent_log_tail'])
    context=bool(re.search(r'context_length_exceeded|maximum context length|context window.{0,40}exceed|prompt.{0,30}too long|input.{0,30}exceeds.{0,20}(?:token|limit)',diagnostic,re.I))
    api=bool(re.search(r'APIError|API error|RateLimitError|rate_limit_exceeded|AuthenticationError|BadRequestError|InternalServerError|Error code: (?:400|401|403|429|500|502|503)|HTTPStatusError',diagnostic,re.I))
    messages=h.get('history') or d.get('messages') or []
    trunc=any(m.get('finish_reason') in ['length','max_tokens','MAX_TOKENS'] for m in messages if isinstance(m,dict))
    return dict(context_limit_evidence=context,truncation_evidence=trunc,api_error_evidence=api,
                timeout_evidence=bool(h.get('timed_out')),wrong_answer=score==0,
                unscored=score is None,success_status=d.get('status')=='success',
                diagnostic_excerpt=diagnostic[-600:] if context or api else '')

def load(r):
    try:
        d=json.loads(Path(r['source_path']).read_text());h={}
        if r.get('history_path') and Path(r['history_path']).exists():
            h=json.loads(Path(r['history_path']).read_text())
            if h.get('session_id')!=r.get('session_id'):h={}
        evidence=classify(d,h,r['score'])
        return dict(benchmark=r['benchmark'],method=r['method'],model=r['model'],group=r['group'],
           question_id=r['question_id'],question_hash=r['question_hash'],repeat=r['repeat'],score=r['score'],
           rounds=h.get('rounds',d.get('rounds')),history_available=bool(h),source_path=r['source_path'],
           history_path=r.get('history_path'),**evidence)
    except Exception as e:return {'load_error':type(e).__name__,'source_path':r['source_path']}

def csvwrite(p,rows):
    if not rows:return
    with p.open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)

def case(r):
    d=json.loads(Path(r['source_path']).read_text());h=json.loads(Path(r['history_path']).read_text()) if r['history_available'] else {}
    messages=h.get('history') or d.get('messages') or []
    evidence='\n'.join(str(m.get('content') or '') for m in messages if isinstance(m,dict) and m.get('role')=='tool')
    answer=str(d.get('answer',''));prediction=str(d.get('model_response',''))
    norm=lambda t:re.sub(r'\s+',' ',t).casefold().strip()
    normalized_evidence=norm(evidence); normalized_answer=norm(answer)
    if re.fullmatch(r'\d+(?:\.\d+)?',normalized_answer):
        match=re.search(r'(?<![\d.])'+re.escape(normalized_answer)+r'(?![\d.])',normalized_evidence)
        pos=match.start() if match else -1
    else:
        pos=normalized_evidence.find(normalized_answer) if normalized_answer else -1
    found=pos>=0
    # Exact answer in retrieved text is evidence of availability, not proof of retention after compression.
    assessment='Reference string occurs in tool evidence; answer selection/retention needs inspection.' if found else 'Reference string absent from available tool text; retrieval gap or answer paraphrase remains possible.'
    if re.search(r'cannot|unable|could not|无法|未能|未找到',prediction,re.I):assessment+=' Final response contains an uncertainty/refusal marker.'
    if not (d.get('compression_stats') or {}).get('compressions'):assessment+=' No positive compression counter in this export: cannot attribute failure to compression.'
    notes={
      ('xbench_deepsearch','109'):'精确汉字/实体消歧错误：输出张宇，reference张羽；同音姓名需要精确字符串证据，尚未证明压缩导致。',
      ('xbench_deepsearch','121'):'题目版本/分支选择冲突：输出同时给出0和另一章节解释下的1；reference为1，最终含歧义。',
      ('seal0','q_002'):'时间范围口径冲突：输出按日历年/赛季分别回答13和11，reference为12。',
      ('seal0','q_003'):'动态票房榜/实体选择冲突：输出Ne Zha 2，reference Zootopia 2；需核对基准日期。',
      ('seal0','q_005'):'精确计数差1：输出IATA成员376，reference377；目录时间或统计范围需核对。',
      ('seal0','q_009'):'版本枚举/支持周期筛选差异：输出10个版本，reference11；需逐项检查遗漏。',
      ('seal0','q_012'):'动态点赞阈值计数差异：输出5，reference4；需核对抓取时间。',
      ('seal0','q_014'):'国籍/居住地分类差异：输出35或33，reference29；答案自身明确采用不同分类口径。',
      ('seal0','q_015'):'视频列表计数缺项或阈值时间差异：输出5项，reference9；需核对完整候选列表。',
      ('seal0','q_004'):'时间锚点/实体选择冲突：reference 为83岁，输出选择John M. Martinis并按2026年计算68岁；需检查数据集参考日期，不能直接归因压缩。',
      ('seal0','q_006'):'输出末尾仍是书目统计代码/工具调用样式，未形成清晰最终数字；需区分输出结束机制与事实遗忘。',
      ('seal0','q_010'):'类别口径冲突：输出明确排除儿歌/教育视频后回答2，而reference为6。',
      ('seal0','q_020'):'动态榜单/计数冲突：输出30减9为21，reference为20；应核对榜单时间和成员。',
      ('seal0','q_021'):'时间口径冲突：输出按2026赛季列出3位，reference为4。',
      ('seal0','q_022'):'枚举/类别筛选差异：输出22名并排除非美国人，reference为31；需要逐项核对。',
      ('seal0','q_026'):'获奖人统计口径差异：输出45位不同个人，reference为20；可能涉及制片人与导演范围。',
      ('seal0','q_027'):'动态阈值名单差异：输出43，reference为41；未证明压缩引起。',
      ('seal0','q_030'):'时间/实体口径冲突：输出选择Faustino Oro并按2026年计算12岁，reference为17岁；需核对年轻纪录与当前最年轻的区别。',
      ('seal0','q_031'):'分项汇总差异：输出Padma 350加Bharat Ratna 1得到351，reference为364；需核对年度原表。',
      ('xbench_deepsearch','102'):'精确实体/标题选择错误：候选论文标题与reference不同；需验证作者机构约束。',
      ('xbench_deepsearch','105'):'答案分支选择错误：输出正文出现reference所需的11，但最终选择另一族裔解释给出2/3。',
      ('xbench_deepsearch','106'):'保存的最终输出为空；仅凭此不能判定检索或压缩原因。',
      ('xbench_deepsearch','111'):'城市实体错误：输出西安，reference武汉；可能混用网络统计年份。',
      ('xbench_deepsearch','113'):'统计口径/事实冲突：输出字频211（并给出37首），reference为3次；需核对题义及语料。',
      ('xbench_deepsearch','115'):'空间证据/座区推断错误：输出108区，reference207区；需现场座位图核验。',
      ('xbench_deepsearch','116'):'输出中断于推理片段，未提供票价；需核对finish reason与运行停止原因。',
      ('xbench_deepsearch','119'):'精确数字/排序错误：输出将变化四舍五入为2/1/1，并将股票置于固定收益前；reference要求2.2/1.1/1.0及精确排序。',
      ('xbench_deepsearch','124'):'输入数值或口径错误：输出44.8/31.61约1.417，reference为1.7；所列除法本身一致。',
      ('xbench_deepsearch','133'):'公司集合/动态管线计数冲突：输出Gilead 31，reference Johnson & Johnson 40；需核对公司分类与时间。',
    }
    return dict(**r,manual_output_review=notes.get((r['benchmark'],r['question_id']),'未人工复核'),question=d.get('question'),reference=answer,prediction=prediction,
       compression_stats=d.get('compression_stats'),reference_exact_in_tool_text=found,
       reference_has_numeric_fact=bool(re.search(r'\d',answer)),
       evidence_excerpt=(norm(evidence)[max(0,pos-180):pos+len(answer)+240] if found else ''),
       assessment=assessment,causal_attribution='unresolved')

def main():
    import os
    os.chdir(ROOT)
    out=ROOT/'outputs/experiment5';doc=ROOT/'docs/experiment5';out.mkdir(parents=True,exist_ok=True);doc.mkdir(parents=True,exist_ok=True)
    raw=[json.loads(l) for l in (ROOT/'outputs/experiment1/reconstructed.jsonl').open()]
    selected=[r for r in raw if r.get('canonical') and r['model']=='gemini-3.5-flash-thinking']
    import sys
    if '--reuse-extracted' in sys.argv and (out/'per_trajectory.jsonl').exists():
        rows=[json.loads(l) for l in (out/'per_trajectory.jsonl').open()]
        prior=json.loads((out/'audit.json').read_text()) if (out/'audit.json').exists() else {}
        rows.extend(prior.get('load_errors',[]))
    else:
        with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(load,selected))
    errors=[r for r in rows if 'load_error' in r];rows=[r for r in rows if 'load_error' not in r]
    (out/'per_trajectory.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    # Keep each archived campaign separate; don't pool 32k and 64k or debug runs.
    grouped=collections.defaultdict(list)
    for r in rows:grouped[r['group']].append(r)
    failures=[];curves=[]
    tags=['context_limit_evidence','truncation_evidence','api_error_evidence','timeout_evidence','wrong_answer','unscored']
    for group,rs in sorted(grouped.items()):
        if rs[0]['method']=='No Compression':
            item=dict(benchmark=rs[0]['benchmark'],model=rs[0]['model'],group=group,n=len(rs),history_available=sum(r['history_available'] for r in rs))
            for t in tags:item[t]=sum(r[t] for r in rs)
            item['wrong_without_observed_runtime_evidence']=sum(r['wrong_answer'] and not any(r[t] for t in tags[:4]) for r in rs)
            item['unscored_without_observed_runtime_evidence']=sum(r['unscored'] and not any(r[t] for t in tags[:4]) for r in rs)
            failures.append(item)
        for b in BINS:
            br=[r for r in rs if bucket(r['rounds'])==b];sc=[r for r in br if r['score'] is not None]
            if br:curves.append(dict(benchmark=rs[0]['benchmark'],model=rs[0]['model'],method=rs[0]['method'],group=group,round_bin=b,n=len(br),scored=len(sc),accuracy=sum(r['score']==1 for r in sc)/len(sc) if sc else None))
    csvwrite(out/'no_compression_failures.csv',failures);csvwrite(out/'accuracy_by_rounds.csv',curves)
    # Fixed deterministic first ten distinct failed questions per benchmark; not selected for a preferred explanation.
    cases=[]
    for bench in ['xbench_deepsearch','seal0']:
        seen=set()
        for r in sorted(rows,key=lambda r:(r['question_id'],str(r['repeat']))):
            if r['benchmark']==bench and r['method']=='VERA' and r['score']==0 and r['question_hash'] not in seen:
                seen.add(r['question_hash']);cases.append(case(r))
                if len(seen)==10:break
    (out/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2))
    audit={'selected_records':len(selected),'parsed_records':len(rows),'load_errors':errors,'case_sampling':'First 10 distinct scored-wrong question IDs per benchmark, lowest available failed repeat. Descriptive, not representative random sample.','no_api_calls':True}
    (out/'audit.json').write_text(json.dumps(audit,indent=2))
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    benches=sorted({r['benchmark'] for r in curves});fig,axs=plt.subplots(2,4,figsize=(17,8),squeeze=False)
    for ax,bench in zip(axs.flat,benches):
        for method in ['No Compression','Discard','Sliding Window','Summarize','VERA']:
            cr=[r for r in curves if r['benchmark']==bench and r['method']==method and r['round_bin']!='missing']
            ax.plot([BINS.index(r['round_bin']) for r in cr],[100*r['accuracy'] if r['accuracy'] is not None else float('nan') for r in cr],marker='o',label=method)
        ax.set_title(bench);ax.set_xticks(range(5),BINS[:5],rotation=20);ax.set_ylabel('Accuracy among scored (%)');ax.set_ylim(0,100);ax.grid(alpha=.2)
    for ax in list(axs.flat)[len(benches):]:ax.set_visible(False)
    handles,labels=axs.flat[0].get_legend_handles_labels();fig.legend(handles,labels,loc='lower center',ncol=5);fig.suptitle('Historical Gemini trajectories: descriptive round bins (not causal or paired)');fig.tight_layout(rect=[0,.05,1,.95]);fig.savefig(doc/'accuracy_by_rounds.png',dpi=150);fig.savefig(out/'accuracy_by_rounds.pdf');plt.close(fig)
    md=['# 实验 5：历史失败与长度分析','',f'离线读取 {len(rows):,} 条 canonical Gemini 轨迹；没有发起模型调用。读取错误 {len(errors)} 条。历史模型、预算和 campaign 保持分组，未混入新 DeepSeek 实验。','',
        '## No Compression 诊断','',
        '各诊断为可重叠标签，分母是该组全部轨迹。日志尾部只能证明错误曾出现，不能证明它是最终失败原因；成功重试也可能留下 API 错误。没有匹配字符串不等于没有发生。wrong 是已有评分为 0，缺失评分单独列出，不能当作答错。截断仅由保存的 finish_reason=length/max_tokens 证明，不凭文本猜测。','',
        '| Benchmark | N | Context 证据 | 截断证据 | API 错误证据 | 超时 | 答错 | 未评分 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in failures:
        fmt=lambda k:f"{r[k]} ({100*r[k]/r['n']:.1f}%)"
        md.append('| '+r['benchmark']+' | '+str(r['n'])+' | '+' | '.join(fmt(k) for k in tags)+' |')
    md+=['','## 按轮数分桶','', '![按轮数的准确率](accuracy_by_rounds.png)','',
         '图按各方法自身的实际轨迹轮数分桶，分桶边界事先固定为 0–10 / 11–30 / 31–60 / 61–100 / 101+。这是描述性关联：题目难度、压缩策略、停止条件都会影响轮数，不能解释为 context rot 的因果测量。各桶样本量和未评分数量见 CSV；不能预先声称 No Compression 必然随长度下降。未对这些探索性曲线提供独立样本置信区间，因为同题重复相关。','',
         '实测例子：BC 的 No Compression 在 31–60 轮桶准确率为 94.1%（85 条有评分），101+ 轮桶为 31.7%（208 条有评分）。但其他方法也普遍在长轨迹桶下降，不能据此将全部差异归因于 No Compression 的上下文退化。日志中未匹配到明确 context-limit 错误；这不是零发生率的证明。','',
         '## VERA 失败样本','', '从 XBench-DeepSearch、Seal-0 各选最小题号的 10 道不同失败题；有重复时取第一个失败 repeat。以下为可审计的初步归因，无法从“答错”直接证明视觉压缩遗忘。完整题目、reference、输出和证据片段保存于 `outputs/experiment5/cases.json`。','']
    for i,c in enumerate(cases,1):
        esc=lambda s:str(s).replace('\n',' ')[:500]
        md += [f"### {i}. {c['benchmark']} / {c['question_id']} / repeat {c['repeat']}", '',f"- 问题：{esc(c['question'])}",f"- Reference：{esc(c['reference'])}",f"- 输出摘录：{esc(c['prediction'])}",f"- 轮数：{c['rounds']}；原文 reference 字符串出现在工具证据中：{c['reference_exact_in_tool_text']}；reference 含数字：{c['reference_has_numeric_fact']}。",f"- 输出对照复核：{c['manual_output_review']}",f"- 初步判断：{c['assessment']}",f"- 原始记录：`{c['source_path']}`",'']
    md += ['## 相关工作与论文修改','',
      '[DeepSeek-V3.2 §4.4](https://arxiv.org/html/2512.02556v1#S4.SS4) 在超过上下文窗口 80% 时触发管理；Discard-all 删除此前工具调用历史，BrowseComp 得到 67.6。其设置说明丢弃历史可通过允许更多执行步骤改善表现，不能直接证明本实验排序具有同一原因。',
      '[Context Rot（Chroma 原始报告）](https://www.trychroma.com/research/context-rot) 研究输入长度增加时的性能变化；[Lost in the Middle](https://arxiv.org/abs/2307.03172) 展示相关信息位置影响模型使用长上下文的能力。两者提供机制假说，不替代这里的受控实验。','',
      '建议将 Finding 3 改写为“在本实验预算和数据集下观察到的趋势”。“统计上持平，且成本更低”仍需对应实验 4 的配对分析和实验 1 的同题成本证据；不显著不等于已证明等效。当前未修改论文主文件。']
    (doc/'experiment5.md').write_text('\n'.join(md)+'\n')
    for p in ['no_compression_failures.csv','accuracy_by_rounds.csv','audit.json']:(doc/p).write_bytes((out/p).read_bytes())
    print(json.dumps(audit));print(json.dumps(failures,ensure_ascii=False))

if __name__=='__main__':main()
