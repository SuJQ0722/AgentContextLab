"""Immutable per-pair route assignment and explicit derived native inputs.

The scientific plan/config/spec remain unchanged. Only derived native model
route and its config pointer differ. Existing legacy claims anchor their pair.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

VERSION='bc-v3-fixed-routes-v1'
ROOT=Path(__file__).resolve().parents[1]
ROUTES=frozenset('deepseek-v4.1-flash-1017/'+suffix for suffix in
                 ('huoshan/huoshan','zijian/sfb','huoshan/sfc','zijian/sfc'))
SOURCE_FILES=('scripts/bc_route_runtime_v1.py','scripts/run_bc_trial_v3_routes1.py',
              'scripts/run_bc_campaign_v3_routes1.py','scripts/hermes_bc_worker_routes1.py',
              'scripts/run_dsh_eval_v3_routes1.py','scripts/route_attribution_routes1.py',
              'scripts/dsh_returned_model_routes1.mjs','scripts/dsh_wire_image_guard_routes1.mjs',
              'scripts/dsh_wire_expectations_routes1.mjs','scripts/dsh_route_guard_routes1.mjs',
              'scripts/dsh_raw_usage_observer.mjs','scripts/hermes_bc_worker.py',
              'scripts/hermes_bc_worker_v3.py','scripts/hermes_native_vision_worker_v2.py',
              'scripts/run_bc_trial_v3.py','scripts/run_bc_trial_v3_io.py','scripts/run_bc_trial_v3_io2.py',
              'scripts/dsh_image_preservation_capacity1.py')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def immutable_json(path,value):
    """Publish a complete, fsynced JSON inode exclusively; never replace a file."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists():
        if json.loads(path.read_text())!=value:raise ValueError('Immutable runtime artifact differs: '+path.name)
        return
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    with temp.open('x') as stream:
        os.chmod(temp,0o600);json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2)
        stream.write('\n');stream.flush();os.fsync(stream.fileno())
    try:
        try:os.link(temp,path)
        except FileExistsError:
            if json.loads(path.read_text())!=value:raise ValueError('Concurrent immutable runtime artifact differs: '+path.name)
        directory=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(directory)
        finally:os.close(directory)
    finally:temp.unlink()


def implementation_hashes():
    # Missing reviewed native entries are a blocker, never a partial identity.
    return {name:sha(ROOT/name) for name in SOURCE_FILES}


class RoutePlan:
    def __init__(self,root,path=None,expected_sha256=None):
        self.root=Path(root).resolve();self.path=Path(path or self.root/'route-plan-v1.json').resolve()
        if expected_sha256 is None:
            expected_sha256=self.path.with_suffix('.sha256').read_text().strip().split()[0]
        if not re.fullmatch(r'[0-9a-f]{64}',expected_sha256):raise ValueError('Explicit fixed route-plan SHA256 required')
        self.expected_sha256=expected_sha256
        route_bytes=self.path.read_bytes()
        if hashlib.sha256(route_bytes).hexdigest()!=self.expected_sha256:raise ValueError('Fixed route plan hash mismatch')
        self.data=json.loads(route_bytes);self.plan_path=self.root/'plan.json'
        plan_bytes=self.plan_path.read_bytes()
        self.plan_sha256=hashlib.sha256(plan_bytes).hexdigest();self.scientific_plan=json.loads(plan_bytes)
        config=json.loads((self.root/'experiment.json').read_text());self.logical_model=config['model']
        if (self.data.get('version')!=VERSION or self.data.get('parent_plan_sha256')!=self.plan_sha256
                or self.data.get('logical_model')!=self.logical_model):
            raise ValueError('Route plan differs from frozen parent/model')
        allowed=self.data.get('allowed_routes')
        if not isinstance(allowed,list) or not allowed or len(set(allowed))!=len(allowed) or not set(allowed)<=ROUTES:
            raise ValueError('Route allowlist must contain unique approved exact 1017 routes')
        if self.logical_model not in allowed:raise ValueError('Original route must remain available for anchored pairs')
        self.jobs={};self.pairs={}
        for job in self.scientific_plan['jobs']:
            if job['model']!=self.logical_model:raise ValueError('Frozen scientific jobs do not share logical model')
            key=(job['question_id'],job['repeat'])
            self.jobs[job['job_id']]=job;self.pairs.setdefault(key,[]).append(job)
        self.assignments={}
        for row in self.data.get('assignments',[]):
            key=(row.get('question_id'),row.get('repeat'))
            if not isinstance(key[0],str) or type(key[1]) is not int or key in self.assignments:
                raise ValueError('Duplicate or invalid pair assignment')
            if key not in self.pairs or row.get('actual_route') not in allowed:raise ValueError('Unplanned pair or route')
            self.assignments[key]=row['actual_route']
        if set(self.assignments)!=set(self.pairs):raise ValueError('Route plan must cover every frozen question/repeat pair')

    def check_unchanged(self):
        if sha(self.path)!=self.expected_sha256:raise ValueError('Fixed route plan changed; no hot route reassignment')

    def bind(self):
        """Persist the campaign's first routes1 identity across controller restarts."""
        self.check_unchanged()
        immutable_json(self.root/'runtime/routes1-plan-binding.json',{
            'version':VERSION,'route_plan_path':str(self.path),'route_plan_sha256':self.expected_sha256,
            'parent_plan_sha256':self.plan_sha256,'logical_model':self.logical_model})

    def assignment(self,job,check_claims=True):
        self.check_unchanged()
        original=self.jobs.get(job['job_id'])
        if original is None or any(job.get(k)!=v for k,v in original.items()):
            raise ValueError('Job differs from original scientific definition')
        key=(original['question_id'],original['repeat']);route=self.assignments[key]
        if check_claims:
            for sibling in self.pairs[key]:
                claim=self.root/'jobs'/sibling['job_id']/'claim'
                if not claim.exists():continue
                owner=json.loads((claim/'owner.json').read_text())
                if owner.get('job_id')!=sibling['job_id']:raise ValueError('Existing claim job identity mismatch')
                actual=owner.get('actual_route',self.logical_model)
                if actual!=route:raise ValueError('Pair is anchored to another route by an existing claim')
                if 'actual_route' in owner and owner.get('route_plan_sha256')!=self.expected_sha256:
                    raise ValueError('Existing routed claim belongs to another route plan')
                if 'actual_route' in owner and owner.get('logical_model')!=self.logical_model:
                    raise ValueError('Existing routed claim has a different logical model')
        return route

    def claim_metadata(self,job):
        return {'logical_model':self.logical_model,'actual_route':self.assignment(job),
                'route_plan_path':str(self.path),'route_plan_sha256':self.expected_sha256,'runtime_route_version':VERSION}


def prepare_runtime(spec,out,route_plan):
    """Called only after the original trial's source/spec/claim validations."""
    out=Path(out)
    route_plan.bind();route=route_plan.assignment(spec)
    original_config=Path(spec['config_path']);config=json.loads(original_config.read_text())
    if config['model']!=route_plan.logical_model:raise ValueError('Original config model mismatch')
    runtime_config={**config,'model':route};config_path=out/'runtime-config.json'
    original_spec={k:v for k,v in spec.items() if k!='_spec_path'}
    runtime_spec={**original_spec,'model':route,'config_path':str(config_path)}
    spec_path=out/'runtime-spec.json'
    immutable_json(config_path,runtime_config);immutable_json(spec_path,runtime_spec)
    lineage={'runtime_route_version':VERSION,'logical_model':route_plan.logical_model,'actual_route':route,
             'route_plan_path':str(route_plan.path),'route_plan_sha256':route_plan.expected_sha256,
             'parent_plan_sha256':route_plan.plan_sha256,'job_id':spec['job_id'],
             'question_id':spec['question_id'],'repeat':spec['repeat'],'harness':spec['harness'],'strategy':spec['strategy'],
             'parent_spec_path':spec['_spec_path'],'parent_spec_sha256':sha(spec['_spec_path']),
             'parent_config_path':str(original_config),'parent_config_sha256':sha(original_config),
             'runtime_spec_path':str(spec_path),'runtime_spec_sha256':sha(spec_path),
             'runtime_config_path':str(config_path),'runtime_config_sha256':sha(config_path),
             'implementation_sha256':implementation_hashes(),
             'allowed_native_diff':['model','config_path (points to model-only derived config)'],
             'route_policy':'Fixed for this question/repeat across harnesses, strategies, retries and auxiliary calls; no intra-trajectory fallback',
             'analysis_policy':'Stratify by actual_route; retain original incurred costs and unknown usage. Catalog aliases do not prove equal backend weights/prices/quotas.'}
    immutable_json(out/'route-lineage.json',lineage)
    return {**runtime_spec,'_spec_path':str(spec_path)},lineage
