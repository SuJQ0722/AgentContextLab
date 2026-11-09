#!/usr/bin/env python3
"""One authorized additional judgment for the second affected sample; never repeats the underlying prediction."""
import argparse
import fcntl
import json
from pathlib import Path
from lab import ROOT,environment
import judge_bc_v3_completed as judge

VERSION='bc-v3-fixed-judge-retry2'
JOB='hermes/none/q_096_r01'


def prepare(grading=judge.DEFAULT_OUT,source=judge.DEFAULT_ROOT):
    grading=Path(grading).resolve();source=Path(source).resolve();base=grading/'sources'/judge.namespace(source)/'jobs'/JOB
    previous=judge.read(base/'grade.json');binding=judge.read(base/'binding.json');config=judge.read(grading/'protocol.json')
    if previous.get('status')!='judge_error' or previous.get('error_type')!='URLError' or previous.get('score') is not None:
        raise ValueError('Authorization covers only this recorded transport judge error')
    if binding.get('job_id')!=JOB or binding.get('root')!=str(source) or previous.get('request_sha256')!=judge.read(base/'request-dispatched.json').get('request_sha256'):
        raise ValueError('Original scoring identity differs')
    if judge.sha(binding['result_path'])!=binding['result_sha256']:raise ValueError('Prediction changed; do not rejudge a different answer')
    if config.get('judge_model')!=judge.MODEL or config.get('max_tokens')!=8192:raise ValueError('Original reviewed judge protocol differs')
    cohort={r['id']:r for r in (json.loads(line) for line in (source/'cohort.jsonl').read_text().splitlines() if line)}
    if judge.sha(source/'cohort.jsonl')!=binding['cohort_sha256']:raise ValueError('Gold cohort changed')
    row=cohort[binding['question_id']];result=judge.read(binding['result_path']);final=result.get('final')
    prediction=final if isinstance(final,str) else final.get('text') if isinstance(final,dict) else None
    if result.get('status')!='completed' or not isinstance(prediction,str):raise ValueError('Original completed prediction unavailable')
    payload={'model':config['judge_model'],'messages':[{'role':'user','content':judge.build_judge_prompt(row['question'],prediction,row['answer'])}],
             'max_tokens':config['max_tokens'],'temperature':config['temperature'],'top_p':config['top_p']}
    if payload!=judge.read(base/'request.json') or judge.sha_bytes(json.dumps(payload,ensure_ascii=False).encode())!=previous['request_sha256']:
        raise ValueError('Additional judgment must use the identical original payload')
    directory=grading/'judge-retry2/jobs'/JOB
    authorization={'version':VERSION,'max_additional_requests':1,'implementation_sha256':judge.sha(__file__),
        'original_protocol_sha256':judge.sha(grading/'protocol.json'),'selection':'Always use additional judge attempt regardless of its result; never choose the higher score',
        'resource_policy':'Original disconnected request has unknown billing/usage. Preserve it and add the new request usage; cumulative cost is not assumed equal to new usage alone.',
        'entries':[{'source_root':str(source),'job_id':JOB,'original_grade_path':str(base/'grade.json'),
            'original_grade_sha256':judge.sha(base/'grade.json'),'new_grade_path':str(directory/'grade.json'),
            'prediction_result_sha256':binding['result_sha256'],'request_sha256':previous['request_sha256']}]}
    judge.immutable(grading/'judge-retry2/selection.json',authorization)
    return {'directory':directory,'binding':binding,'question':row['question'],'prediction':prediction,'answer':row['answer']},config,authorization


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--live',action='store_true');args=ap.parse_args()
    candidate,config,authorization=prepare()
    if not args.live:
        print(json.dumps({'live':False,'job_id':JOB,'additional_model_requests_at_most':1,'prediction_reruns':0}));return
    directory=candidate['directory'];directory.mkdir(parents=True,exist_ok=True)
    lock=(directory/'controller.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    env,_=environment(ROOT,'dsh',judge.DEFAULT_ROOT/'experiment.json')
    result=judge.grade(candidate,config,env)
    print(json.dumps({k:result.get(k) for k in ['status','score','http_status','error_type','raw_provider_usage','usage','usd']}))


if __name__=='__main__':main()
