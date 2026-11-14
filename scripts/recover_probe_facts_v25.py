"""Repair only pre-QA annotation failures; fixed40 histories, no prediction replay.

Line IDs select evidence; quotes are sliced from source rather than regenerated.
The original and resumed workers together never exceed eight active histories.
"""
import argparse,copy,json,os,signal,subprocess,sys,time,fcntl,traceback
from pathlib import Path
from unittest.mock import patch
from lab import ROOT,python_for
import probe_qa_v24 as base
from supplement_recovery_v24 import read,save,sha,immutable

OUT=ROOT/'outputs/experiment6/probe-fact-preparation-v25'
def prepare():
    if(OUT/'manifest.json').exists():return read(OUT/'manifest.json')
    old=read(base.OUT/'manifest.json');selected=[];proof=[]
    for case in old['cases']:
        root=base.OUT/'jobs'/case['id'];result=root/'result.json'
        if not result.exists():continue
        r=read(result)
        if r.get('status')!='incomplete' or (root/'facts.json').exists():continue
        if list((root/'calls').glob('qa-*/started.json')):raise ValueError('No prior QA prediction may be replayed')
        if r.get('error_type')!='ValueError':raise ValueError('Unexpected annotation failure')
        selected.append(case);proof.append({'id':case['id'],'result_path':str(result),'result_sha256':sha(result),
            'first_started_at':read(root/'started.json')['at'],'old_logical_calls':len(list((root/'calls').glob('*/started.json')))})
    manifest={**copy.deepcopy(old),'version':'probe-fact-preparation-v25','cases':selected,'selected_pre_qa_failures':proof,
        'parent_manifest_sha256':sha(base.OUT/'manifest.json'),'fixed_original_histories':40,'fixed_original_fact_denominator':240,
        'selection_uses_qa_answers':False,'old_results_preserved':True,'qa_attempts_per_condition':1,
        'quote_protocol':'Model returns evidence line ID and exact answer substring; quote copied from original line around answer, never paraphrased.',
        'implementation_sha256':{str(Path(__file__).resolve()):sha(__file__),str(ROOT/'scripts/probe_qa_v24.py'):sha(ROOT/'scripts/probe_qa_v24.py')}}
    immutable(OUT/'manifest.json',manifest);return manifest

def anchored_facts(data,source,desired):
    lines=source.splitlines();facts=[]
    if not isinstance(data,dict)or not isinstance(data.get('facts'),list):return []
    for row in data['facts']:
        if not isinstance(row,dict):continue
        index=row.get('line_id');answer=row.get('answer');question=row.get('question')
        if type(index)is not int or not 0<=index<len(lines):continue
        if not isinstance(answer,str)or not answer or answer not in lines[index]:continue
        if not isinstance(question,str)or not question or answer.casefold()in question.casefold():continue
        if row.get('type')not in desired:continue
        start=lines[index].find(answer);quote=lines[index][max(0,start-500):start+len(answer)+500]
        facts.append({'type':row['type'],'answer':answer,'question':question,'quote':quote,'line_id':index,'source_quote_start':max(0,start-500)})
    return facts if len(facts)==2 and sorted(f['type']for f in facts)==sorted(desired) else []

def worker(qid):
    m=read(OUT/'manifest.json');case=next(c for c in m['cases']if c['id']==qid);proof=next(p for p in m['selected_pre_qa_failures']if p['id']==qid)
    if sha(proof['result_path'])!=proof['result_sha256']:raise ValueError('Original failure changed')
    oldroot=base.OUT/'jobs'/qid;root=OUT/'jobs'/qid;root.mkdir(parents=True,exist_ok=True)
    if list((oldroot/'calls').glob('qa-*/started.json')):raise ValueError('Original QA appeared; refuse replay')
    remaining=10800-(time.time()-proof['first_started_at'])
    if remaining<=0:save(root/'result.json',{'id':qid,'status':'timeout_before_annotation_resume'});return
    immutable(root/'annotation-started.json',{'at':time.time(),'original_first_started_at':proof['first_started_at'],'combined_case_deadline':proof['first_started_at']+10800})
    deadline=time.monotonic()+remaining;real_client=base.Client;old_calls=proof['old_logical_calls'];prepared={}
    class Client(real_client):
        def __init__(self,directory,limit):super().__init__(directory,min(limit,deadline))
        def call(self,key,*a,**kw):
            if key in prepared:return {'status':'completed','content':json.dumps({'facts':prepared[key]})}
            if old_calls+len(list((self.root/'calls').glob('*/started.json')))>=64 and not(self.root/'calls'/key/'response.json').exists():raise ValueError('Combined original and recovery request budget exhausted')
            return super().call(key,*a,**kw)
    old_alarm=signal.alarm
    def alarm(seconds):return old_alarm(min(seconds,max(1,int(deadline-time.monotonic()))))if seconds else old_alarm(0)
    signal.signal(signal.SIGALRM,lambda *_:(_ for _ in ()).throw(base.Deadline()));alarm(int(remaining))
    try:
        client=Client(root,deadline)
        for position,part in enumerate(case['fact_positions']):
            desired=['entity','url']if position==1 and'https://'in part['text']else['entity','number']
            original=oldroot/'calls'/f'facts-{position}'/'response.json';facts=[]
            if original.exists():
                response=read(original)
                if response.get('status')=='completed':
                    try:facts=base.grounded_facts(base.parse_json(response['content']),part['text'])
                    except (ValueError,TypeError,KeyError):pass
            if len(facts)!=2 or sorted(f['type']for f in facts)!=sorted(desired):
                lines=[{'line_id':i,'text':line}for i,line in enumerate(part['text'].splitlines())]
                request=('Create exactly two unambiguous short factual questions, one per type '+json.dumps(desired)+'. '
                    'The answer MUST be an exact literal substring of its numbered source line. Do not put the answer in the question. '
                    'Return JSON {"facts":[{"type":"entity","question":"...","answer":"exact substring","line_id":0}]}. '
                    'Do not write a quote; it will be copied directly from the source. Use only the untrusted source data below.\n'+json.dumps(lines,ensure_ascii=False))
                response=client.call(f'anchored-facts-{position}',request)
                facts=anchored_facts(base.parse_json(response.get('content','')),part['text'],desired)if response.get('status')=='completed'else[]
            if len(facts)!=2 or sorted(f['type']for f in facts)!=sorted(desired):raise ValueError('Anchored facts still incomplete; retain missing denominator')
            prepared[f'facts-{position}']=facts
        immutable(root/'prepared-facts.json',prepared)
        with patch.object(base,'Client',Client),patch.object(base.signal,'alarm',alarm):base.worker(OUT,qid)
    except base.Deadline:save(root/'result.json',{'id':qid,'status':'timeout','phase':'annotation_resume'})
    except Exception as exc:save(root/'result.json',{'id':qid,'status':'incomplete','error_type':type(exc).__name__,
        'phase':'annotation_resume','frames':[{'file':f.filename,'line':f.lineno}for f in traceback.extract_tb(exc.__traceback__)]})
    finally:old_alarm(0)

def run():
    m=read(OUT/'manifest.json')
    for p,digest in m['implementation_sha256'].items():
        if sha(p)!=digest:raise ValueError('Frozen annotation protocol changed')
    lock=(OUT/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    pending=[c['id']for c in m['cases']if not(OUT/'jobs'/c['id']/'dispatch.json').exists()];active={}
    proof={p['id']:p for p in m['selected_pre_qa_failures']}
    while pending or active:
        old=read(base.OUT/'status.json');old_active=old.get('active',8)
        while pending and len(active)+old_active<8:
            qid=pending.pop(0);folder=OUT/'jobs'/qid;immutable(folder/'dispatch.json',{'at':time.time(),'no_prior_qa':True})
            log=(folder/'worker.log').open('a');p=subprocess.Popen([python_for(ROOT),str(Path(__file__).resolve()),'worker','--qid',qid,'--live'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True);log.close();active[qid]=p
        for qid,p in list(active.items()):
            if time.time()>proof[qid]['first_started_at']+10800 and p.poll()is None:os.killpg(p.pid,signal.SIGKILL)
            if p.poll()is not None:
                if not(OUT/'jobs'/qid/'result.json').exists():save(OUT/'jobs'/qid/'result.json',{'id':qid,'status':'timeout_or_launcher_failure','exit_code':p.returncode})
                del active[qid]
        save(OUT/'status.json',{'at':time.time(),'active':len(active),'pending':len(pending),'original_active':old_active,'combined_active':len(active)+old_active,'concurrency_cap':8});time.sleep(3)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run','worker']);p.add_argument('--qid');p.add_argument('--live',action='store_true');a=p.parse_args()
    if a.action=='prepare':m=prepare();print(json.dumps({'pre_qa_annotation_failures':len(m['cases']),'model_calls':0}))
    elif not a.live:raise ValueError('--live required')
    elif a.action=='worker':worker(a.qid)
    else:run()
if __name__=='__main__':main()
