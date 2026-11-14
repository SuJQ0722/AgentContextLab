"""One new grading attempt for already completed, previously unscored predictions."""
import argparse,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from lab import ROOT,environment
from supplement_recovery_v24 import DEFAULT,read,sha,source_job
from report_supplement_v24 import grade
from judge_visual_hosted_retry_v1 import gold_sources
from judge_controlled_source_v20 import valid_control
import judge_bc_v3_completed as bc

OUT=ROOT/'outputs/grading/missing-completed-v24'
def main():
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');a=p.parse_args()
    gold,hashes=gold_sources();candidates=[]
    sources=DEFAULT/'sources'
    rows=[r for r in read(sources/'core.json')['observations'] if not(r['benchmark']=='mmbc100'and r['method']=='visual')]+read(sources/'overlay.json')['observations']
    for row in rows:
        if row['status']!='completed_ungraded':continue
        rp=Path(row['latest_terminal_result_path']);job,_=source_job(rp)
        candidates.append((row['slot_id'],rp,job['question_id'],'mmbc'if row['benchmark']=='mmbc100'else'bc',job['question']))
    plans=[ROOT/'outputs/controlled-mmbc-vera-nontimeout-v20/plan.json',ROOT/'outputs/controlled-mmbc-vera-nontimeout-summary-v23/plan.json']
    jobs={j['job_id']:j for p in plans for j in read(p)['jobs']}
    for row in read(sources/'controlled.json')['rows']:
        if row['status']!='completed'or row.get('score')is not None or not row.get('control_valid'):continue
        j=jobs[row['job_id']];rp=Path(j['output_path'])/'native-result.json';native=read(rp)
        if not valid_control(native.get('control_gate')or{},read(j['target_path'])):raise ValueError('Controlled gate changed')
        candidates.append(('controlled:'+row['job_id'],rp,j['question_id'],'mmbc',read(j['spec_path'])['question']))
    pending=[];OUT.mkdir(parents=True,exist_ok=True);OUT.chmod(0o700)
    for slot,rp,qid,key,question in candidates:
        secret=gold[key][qid]
        if secret['question']!=question:raise ValueError('Gold question differs')
        result=read(rp)
        if result['status']!='completed':raise ValueError('Only existing completions can be rejudged')
        final=result.get('final');prediction=final if isinstance(final,str)else(final or{}).get('text','')
        directory=OUT/'jobs'/bc.sha_bytes(slot.encode())[:20]
        binding={'slot_id':slot,'result_path':str(rp),'result_sha256':sha(rp),'gold_sources_sha256':hashes,'prediction_sha256':bc.sha_bytes(prediction.encode())}
        pending.append({'directory':directory,'binding':binding,'question':question,'answer':secret['answer'],'prediction':prediction})
    bc.immutable(OUT/'manifest.json',{'slots':[c['binding']for c in pending],'new_prediction_attempts':0,'new_judge_attempts_per_slot':1})
    if a.live:
        env,_=environment(ROOT,'hermes');cfg={'judge_model':bc.MODEL,'max_tokens':8192,'temperature':0,'top_p':1,'timeout_seconds':180}
        with ThreadPoolExecutor(max_workers=2)as pool:list(pool.map(lambda c:grade(c,cfg,env),pending))
    print(json.dumps({'selected_completed_predictions':len(pending),'prediction_calls':0,'live':a.live}))
if __name__=='__main__':main()
