"""Immutable per-pair route assignment and explicit derived native inputs.

Explicit revision: only previously unclaimed sfc pairs may move to sfb.
The scientific plan/config/spec remain unchanged. Only derived native model
route and its config pointer differ. Existing legacy claims anchor their pair.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
import fcntl
from contextlib import contextmanager
from bc_route_runtime_v1 import RoutePlan as ParentRoutePlan, SOURCE_FILES as PARENT_SOURCE_FILES
from run_bc_campaign_v3 import owner_alive, same_host

VERSION='bc-v3-fixed-routes-v2'
ROOT=Path(__file__).resolve().parents[1]
ROUTES=frozenset('deepseek-v4.1-flash-1017/'+suffix for suffix in
                 ('huoshan/huoshan','zijian/sfb','huoshan/sfc','zijian/sfc'))
SOURCE_FILES=PARENT_SOURCE_FILES+('scripts/bc_route_runtime_v2.py',
    'scripts/run_bc_trial_v3_routes2.py','scripts/run_bc_campaign_v3_routes2.py','scripts/run_bc_campaign_v3.py')

MIGRATABLE_ROUTES=frozenset('deepseek-v4.1-flash-1017/'+suffix for suffix in ('huoshan/sfc','zijian/sfc'))
VALIDATED_TARGET='deepseek-v4.1-flash-1017/zijian/sfb'


class ParentPreparationPending(RuntimeError):
    """A parent trial may still check siblings against its immutable v1 hash."""


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


class RoutePlanV2:
    def __init__(self,root,path=None,expected_sha256=None):
        self.root=Path(root).resolve();self.path=Path(path or self.root/'route-plan-v2.json').resolve()
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

        parent_path=self.data.get('parent_route_plan_path');parent_sha=self.data.get('parent_route_plan_sha256')
        if not isinstance(parent_path,str) or not Path(parent_path).is_absolute() or not isinstance(parent_sha,str):
            raise ValueError('Explicit absolute parent route-plan path and SHA256 required')
        self.parent=ParentRoutePlan(self.root,parent_path,parent_sha)
        if self.path==self.parent.path:raise ValueError('Revision must not overwrite parent route plan')
        if set(allowed)!=set(self.parent.data['allowed_routes']):raise ValueError('Revision cannot alter approved route allowlist')
        if not isinstance(self.data.get('revision_reason'),str) or not self.data['revision_reason'].strip():
            raise ValueError('Explicit route revision reason required')
        self.changed_pairs={key for key in self.pairs if self.assignments[key]!=self.parent.assignments[key]}
        if not self.changed_pairs:raise ValueError('Revision contains no changed pair')
        for key in self.changed_pairs:
            if self.parent.assignments[key] not in MIGRATABLE_ROUTES or self.assignments[key]!=VALIDATED_TARGET:
                raise ValueError('Only unclaimed rejected sfc pairs may migrate to validated sfb')
        self.binding_path=self.root/'runtime/routes2-plan-binding.json'
        self.parent_binding_path=self.root/'runtime/routes1-plan-binding.json'
        ack_path=self.data.get('cutover_ack_path');ack_sha=self.data.get('cutover_ack_sha256')
        if (not isinstance(ack_path,str) or not Path(ack_path).is_absolute()
                or not isinstance(ack_sha,str) or not re.fullmatch(r'[0-9a-f]{64}',ack_sha)):
            raise ValueError('Explicit immutable cutover acknowledgement path and SHA256 required')
        self.cutover_ack_path=Path(ack_path).resolve();self.cutover_ack_sha256=ack_sha
        self.check_unchanged()
        if not self.binding_path.exists():self.validate_claims()

    def _parent_binding(self):
        return {'version':self.parent.data['version'],'route_plan_path':str(self.parent.path),
            'route_plan_sha256':self.parent.expected_sha256,'parent_plan_sha256':self.plan_sha256,
            'logical_model':self.logical_model}

    def _binding(self):
        return {'version':VERSION,'route_plan_path':str(self.path),'route_plan_sha256':self.expected_sha256,
            'parent_route_plan_path':str(self.parent.path),'parent_route_plan_sha256':self.parent.expected_sha256,
            'parent_plan_sha256':self.plan_sha256,'logical_model':self.logical_model,
            'cutover_ack_path':str(self.cutover_ack_path),'cutover_ack_sha256':self.cutover_ack_sha256,
            'changed_pairs':len(self.changed_pairs)}

    def check_unchanged(self):
        if sha(self.path)!=self.expected_sha256:raise ValueError('Fixed route plan changed; no hot route reassignment')
        self.parent.check_unchanged()
        if sha(self.plan_path)!=self.plan_sha256:raise ValueError('Original scientific plan changed')
        if json.loads(self.parent_binding_path.read_text())!=self._parent_binding():
            raise ValueError('Original routes1 binding missing or differs; never replace it')
        if self.binding_path.exists() and json.loads(self.binding_path.read_text())!=self._binding():
            raise ValueError('Existing routes2 binding differs')
        if sha(self.cutover_ack_path)!=self.cutover_ack_sha256:raise ValueError('Cutover acknowledgement changed')

    def check_cutover(self,live=False):
        ack=json.loads(self.cutover_ack_path.read_text())
        if ack.get('schema')!='routes2-dispatch-cutover-v1' or ack.get('parent_route_plan_sha256')!=self.parent.expected_sha256:
            raise ValueError('Cutover acknowledgement belongs to another parent plan')
        config_path=Path(ack.get('dispatch_config_path','/missing'))
        if not config_path.is_absolute() or sha(config_path)!=ack.get('dispatch_config_sha256'):
            raise ValueError('Cutover dispatch configuration differs')
        config=json.loads(config_path.read_text())
        if any(config.get(k,{}).get(route)!=0 for k in ('per_route_cloud_caps','per_route_local_caps') for route in MIGRATABLE_ROUTES):
            raise ValueError('Rejected parent routes must remain cap zero at cutover')
        snapshots=ack.get('controller_statuses')
        if not isinstance(snapshots,list) or not snapshots:raise ValueError('Explicit stopped controller acknowledgements required')
        inactive=ack.get('inactive_local_controllers',[])
        if not isinstance(inactive,list):raise ValueError('Invalid inactive local controller evidence')
        sources=set();inactive_sources=set()
        for entry,is_inactive in [(e,False) for e in snapshots]+[(e,True) for e in inactive]:
            snapshot=Path(entry.get('snapshot_path','/missing'));source=Path(entry.get('source_path','/missing'))
            if (not snapshot.is_absolute() or not source.is_absolute() or snapshot.resolve()==source.resolve()
                    or sha(snapshot)!=entry.get('snapshot_sha256')):
                raise ValueError('Invalid immutable controller stop snapshot')
            saved=json.loads(snapshot.read_text())
            if not is_inactive and saved.get('stop_dispatch') is not True:raise ValueError('Controller has not acknowledged stopping dispatch')
            if source.resolve() in sources:raise ValueError('Duplicate controller acknowledgement')
            sources.add(source.resolve())
            if live:
                current=json.loads(source.read_text())
                if is_inactive:
                    if (not same_host(current) or owner_alive(current) is not False
                            or not current.get('start_identity') or type(current.get('pid')) is not int):
                        raise ValueError('Inactive controller requires same-host exact process identity proven gone')
                    inactive_sources.add(source.resolve())
                elif current.get('stop_dispatch') is not True:raise ValueError('Controller resumed dispatch after acknowledgement')
                for key in ('hostname','boot_id','pid_namespace','pid','start_identity'):
                    if key in saved and current.get(key)!=saved[key]:raise ValueError('Controller identity differs at cutover')
        if live:
            # Frozen v1 controllers do not take the v2 lock. The explicit barrier,
            # rather than that lock alone, prevents cross-generation claims.
            for status in (self.root/'controllers').glob('*/status.json'):
                current=json.loads(status.read_text())
                if current.get('stop_dispatch') is not True and status.resolve() not in inactive_sources:
                    raise ValueError('Unacknowledged predecessor controller may still dispatch')
                if status.resolve() not in sources:
                    raise ValueError('Cutover acknowledgement omitted a predecessor controller')

    @contextmanager
    def claim_lock(self):
        runtime=self.root/'runtime';runtime.mkdir(parents=True,exist_ok=True)
        with (runtime/'routes2-transition.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            try:yield
            finally:fcntl.flock(lock,fcntl.LOCK_UN)

    def _check_pair_claims(self,key):
        route=self.assignments[key]
        for sibling in self.pairs[key]:
            jobdir=self.root/'jobs'/sibling['job_id'];claim=jobdir/'claim'
            if not claim.exists():
                if key in self.changed_pairs and (jobdir/'attempts').exists():
                    raise ValueError('Changed pair has an attempt without a claim')
                continue
            owner=json.loads((claim/'owner.json').read_text())
            if owner.get('job_id')!=sibling['job_id']:raise ValueError('Existing claim job identity mismatch')
            actual=owner.get('actual_route',self.logical_model)
            if actual!=route:raise ValueError('Pair is anchored to another route by an existing claim')
            if 'actual_route' not in owner:
                if any(k in owner for k in ('route_plan_sha256','route_plan_path','runtime_route_version','logical_model')):
                    raise ValueError('Incomplete routed claim cannot be treated as legacy')
                if key in self.changed_pairs or route!=self.logical_model:
                    raise ValueError('Changed pair has a pre-revision legacy claim')
                continue
            if owner.get('logical_model')!=self.logical_model:raise ValueError('Claim logical model differs')
            claim_sha=owner.get('route_plan_sha256')
            if claim_sha==self.expected_sha256:
                if (not self.binding_path.exists() or owner.get('runtime_route_version')!=VERSION
                    or Path(owner.get('route_plan_path','/missing')).resolve()!=self.path
                    or owner.get('parent_route_plan_sha256')!=self.parent.expected_sha256
                    or Path(owner.get('parent_route_plan_path','/missing')).resolve()!=self.parent.path):
                    raise ValueError('Revision claim lacks exact existing routes2 binding')
            elif claim_sha==self.parent.expected_sha256:
                if (key in self.changed_pairs or actual!=self.parent.assignments[key]
                    or owner.get('runtime_route_version')!=self.parent.data['version']
                    or Path(owner.get('route_plan_path','/missing')).resolve()!=self.parent.path):
                    raise ValueError('Changed pair has a pre-revision routes1 claim or invalid parent lineage')
            else:raise ValueError('Existing routed claim belongs to neither exact parent nor revision')

    def validate_claims(self):
        self.check_unchanged()
        for key in self.pairs:self._check_pair_claims(key)

    def bind(self):
        """New binding only; original routes1 binding remains byte-for-byte intact."""
        with self.claim_lock():
            self.check_unchanged()
            if self.binding_path.exists():return  # Per-job sibling checks still run before every claim/native launch.
            self.validate_claims()
            if not self.binding_path.exists():
                self.check_cutover(live=True)
                for key in self.changed_pairs:
                    if any((self.root/'jobs'/job['job_id']/name).exists() for job in self.pairs[key] for name in ('claim','attempts')):
                        raise ValueError('Every revised pair must have no claim or attempt at first binding')
            immutable_json(self.binding_path,self._binding())
            self.validate_claims()

    def assignment(self,job,check_claims=True):
        self.check_unchanged()
        original=self.jobs.get(job['job_id'])
        if original is None or any(job.get(k)!=v for k,v in original.items()):
            raise ValueError('Job differs from original scientific definition')
        key=(original['question_id'],original['repeat'])
        if check_claims:self._check_pair_claims(key)
        return self.assignments[key]

    def claim_metadata(self,job):
        if not self.binding_path.exists():raise ValueError('Bind routes2 before claiming new work')
        key=(job['question_id'],job['repeat'])
        for sibling in self.pairs[key]:
            jobdir=self.root/'jobs'/sibling['job_id'];claim=jobdir/'claim/owner.json'
            if not claim.exists():continue
            owner=json.loads(claim.read_text())
            if owner.get('route_plan_sha256')!=self.parent.expected_sha256:continue
            attempt=jobdir/'attempts/attempt_001'
            if (attempt/'result.json').exists():
                result=json.loads((attempt/'result.json').read_text())
                if result.get('status') in {'completed','failed','timeout','interrupted','not_started'}:continue
            lineage=attempt/'route-lineage.json'
            if lineage.exists() and (attempt/'worker-started.json').exists():
                value=json.loads(lineage.read_text())
                if (value.get('route_plan_sha256')==self.parent.expected_sha256
                    and value.get('job_id')==sibling['job_id']
                    and value.get('actual_route')==self.parent.assignments[key]):continue
            raise ParentPreparationPending('Parent routes1 sibling has not finished runtime preparation: '+sibling['job_id'])
        return {'logical_model':self.logical_model,'actual_route':self.assignment(job),
                'route_plan_path':str(self.path),'route_plan_sha256':self.expected_sha256,
                'parent_route_plan_path':str(self.parent.path),'parent_route_plan_sha256':self.parent.expected_sha256,
                'runtime_route_version':VERSION}


RoutePlan=RoutePlanV2


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
             'parent_route_plan_path':str(route_plan.parent.path),'parent_route_plan_sha256':route_plan.parent.expected_sha256,
             'cutover_ack_path':str(route_plan.cutover_ack_path),'cutover_ack_sha256':route_plan.cutover_ack_sha256,
             'revision_reason':route_plan.data['revision_reason'],
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
