#!/usr/bin/env python3
"""Scope-checked .75-only adapter around the unchanged one-request judge protocol."""
import argparse
from collections import Counter
from pathlib import Path
import sys
import judge_bc_v3_completed as shared
from prepare_rq3_scale0750_v1 import DEFAULT_ROOT,GRADING,MANIFEST,validate_scope
from lab import ROOT
VERSION='rq3-scale0750-private-grading-scope-v1'

class ScopeGuard:
    def __init__(self,root):
        self.root=Path(root).resolve();plan,self.manifest=validate_scope(self.root)
        self.plan_sha=shared.sha(self.root/'plan.json');self.scope_sha=shared.sha(self.root/MANIFEST)
        self.authorized=set(self.manifest['authorized_job_ids'])
        self.jobs=[j for j in plan['jobs'] if j['job_id'] in self.authorized]
    def check(self):
        if shared.sha(self.root/'plan.json')!=self.plan_sha or shared.sha(self.root/MANIFEST)!=self.scope_sha:
            raise ValueError('Frozen .75 grading scope changed')
    def candidate(self,candidate):
        self.check();binding=candidate['binding'];jid=binding.get('job_id')
        if jid not in self.authorized or Path(binding['root']).resolve()!=self.root:raise ValueError('Judge candidate is outside authorized .75 scope')
        expected=self.root/'jobs'/jid/'attempts/attempt_001'
        if Path(binding['attempt_path']).resolve()!=expected or Path(binding['result_path']).resolve()!=expected/'result.json':raise ValueError('Judge candidate attempt differs')
    def inventory(self,original,root,output,cohort):
        self.check()
        if Path(root).resolve()!=self.root:raise ValueError('Unexpected grading root')
        candidates,info=original(root,output,cohort)
        for candidate in candidates:self.candidate(candidate)
        states=Counter()
        for job in self.jobs:
            path=self.root/'jobs'/job['job_id']/'attempts/attempt_001/result.json'
            states[shared.read(path).get('status','unknown') if path.exists() else 'no_terminal_result']+=1
        return candidates,{**info,'planned':len(self.authorized),'declared_plan_runs':2100,'nonexecutable_placeholders':1800,
            'prediction_states':dict(states),'scope_version':VERSION,'scope_manifest_sha256':self.scope_sha,
            'candidate_scope_verified':True}
    def grade(self,original,candidate,config,env,**kwargs):
        self.candidate(candidate)
        return original(candidate,config,env,**kwargs)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=DEFAULT_ROOT);p.add_argument('--output',type=Path,default=GRADING)
    p.add_argument('--live',action='store_true');p.add_argument('--watch',action='store_true');p.add_argument('--concurrency',type=int,choices=[1],default=1);a=p.parse_args()
    guard=ScopeGuard(a.root);out=a.output.resolve()
    if out.is_relative_to(guard.root):raise ValueError('Gold grading namespace must remain outside native campaign')
    shared.immutable(out/'scope-runtime.json',{'version':VERSION,'root':str(guard.root),'plan_sha256':guard.plan_sha,'scope_sha256':guard.scope_sha,
        'authorized_runs':300,'concurrency':1,'source_sha256':shared.sha(__file__),'shared_judge_sha256':shared.sha(shared.__file__),
        'source_scope_validator_sha256':shared.sha(ROOT/'scripts/prepare_rq3_scale0750_v1.py'),
        'judge_protocol_unchanged':True,'paid_request_retry_added':False})
    old_inventory=shared.source_inventory;old_grade=shared.grade;old_argv=sys.argv
    shared.source_inventory=lambda root,output,cohort:guard.inventory(old_inventory,root,output,cohort)
    shared.grade=lambda candidate,config,env,**kwargs:guard.grade(old_grade,candidate,config,env,**kwargs)
    sys.argv=[shared.__file__,'--root',str(guard.root),'--output',str(out),'--environment-config',str(guard.root/'experiment.json'),'--concurrency','1']
    if a.live:sys.argv.append('--live')
    if a.watch:sys.argv.append('--watch')
    try:shared.main()
    finally:shared.source_inventory=old_inventory;shared.grade=old_grade;sys.argv=old_argv
if __name__=='__main__':main()
