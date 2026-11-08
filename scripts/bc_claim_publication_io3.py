"""Operational metadata-publication handling; frozen routes2 policy is unchanged."""
import hashlib
import json
from pathlib import Path
import time
from bc_route_runtime_v2 import RoutePlanV2, ParentPreparationPending, immutable_json

VERSION='bc-v3-claim-publication-io3'
ROOT=Path(__file__).resolve().parents[1]
SOURCE_FILES=('scripts/bc_claim_publication_io3.py','scripts/run_bc_campaign_v3_routes2_io3.py',
              'scripts/run_bc_trial_v3_routes2_io3.py','scripts/bc_route_runtime_v2.py',
              'scripts/run_bc_campaign_v3_routes2.py','scripts/run_bc_trial_v3_routes2.py',
              'scripts/run_dsh_eval_v3_routes2_io3.py')
RETRY_DELAYS=(.1,.25,.5,1,2,4,8,8,8,8)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def operational_record():
    return {'version':VERSION,'implementation_sha256':{p:sha(ROOT/p) for p in SOURCE_FILES},
            'scope':'Only missing claim-owner publication; no API retry, new attempt, claim rewrite or source guard bypass',
            'native_entry_override':{'dsh':'scripts/run_dsh_eval_v3_routes2_io3.py',
                'change':'Insert CLI end-of-options separator before the unchanged question; guards and original route lineage retained'},
            'max_metadata_wait_seconds':sum(RETRY_DELAYS),'native_runtime_lineage':'Frozen routes2 prepare_runtime and its implementation hashes unchanged'}


def verify_operational_record(path):
    record=json.loads(Path(path).read_text())
    if record!=operational_record():raise ValueError('Operational io3 source identity changed before native launch')
    return record


class ClaimPublicationPending(ParentPreparationPending):
    pass


def missing_owner(exc,paths):
    return isinstance(exc,FileNotFoundError) and exc.filename is not None and Path(exc.filename).resolve() in {Path(p).resolve() for p in paths}


class PublicationRoutePlan(RoutePlanV2):
    """Controller: incomplete sibling ownership is pending, never an empty legacy claim."""
    def _check_pair_claims(self,key):
        try:return super()._check_pair_claims(key)
        except FileNotFoundError as exc:
            paths=[self.root/'jobs'/j['job_id']/'claim/owner.json' for j in self.pairs[key]]
            if missing_owner(exc,paths):raise ClaimPublicationPending('Sibling claim owner is not published yet') from exc
            raise

    def claim_metadata(self,job):
        key=(job['question_id'],job['repeat'])
        try:return super().claim_metadata(job)
        except FileNotFoundError as exc:
            paths=[self.root/'jobs'/j['job_id']/'claim/owner.json' for j in self.pairs[key]]
            if missing_owner(exc,paths):raise ClaimPublicationPending('Sibling claim owner is not published yet') from exc
            raise


def retry_publication(operation,*,delays=RETRY_DELAYS,sleep=time.sleep,on_wait=None):
    """Retries exactly the narrow pending exception. Malformed or conflicting owners fail."""
    for index in range(len(delays)+1):
        try:return operation()
        except ClaimPublicationPending:
            if index==len(delays):raise
            if on_wait:on_wait(index+1,delays[index])
            sleep(delays[index])


class StartupRoutePlan(PublicationRoutePlan):
    """Trial: bounded metadata wait before the original native dispatch boundary."""
    retry_delays=RETRY_DELAYS
    sleep=staticmethod(time.sleep)
    on_wait=None
    def _check_pair_claims(self,key):
        return retry_publication(lambda:super(StartupRoutePlan,self)._check_pair_claims(key),
                                 delays=self.retry_delays,sleep=self.sleep,on_wait=self.on_wait)


def wait_for_owned_metadata(spec,*,delays=RETRY_DELAYS,sleep=time.sleep,on_wait=None):
    """Readiness only. Original validate_spec still validates every ownership field once."""
    root=Path(spec['campaign_root'])
    paths=[root/'jobs'/spec['job_id']/'claim/owner.json',Path(spec['slot_path'])/'owner.json']
    def ready():
        try:
            for path in paths:json.loads(path.read_text())
        except FileNotFoundError as exc:
            if missing_owner(exc,paths):raise ClaimPublicationPending('Own claim or slot owner not published yet') from exc
            raise
    return retry_publication(ready,delays=delays,sleep=sleep,on_wait=on_wait)


NEVER_STARTED_FILES=frozenset(('launcher.log','runtime-config.json','runtime-spec.json','route-lineage.json',
    'maintenance.json','claim-publication-io3.json','claim-publication-io3-events.jsonl','claim-publication-recovery.json',
    'claim-publication-recovery-dispatch.json'))


def check_never_started(out):
    out=Path(out)
    if not out.exists():return
    unexpected=[p.name for p in out.iterdir() if not p.is_file() or p.name not in NEVER_STARTED_FILES]
    if unexpected:raise ValueError('Attempt has started, terminal, native or unknown evidence; no recovery: '+','.join(sorted(unexpected)))


def validate_recovery(spec,spec_path,out,authorization_path):
    """Strict explicit recovery of a never-started claim in a terminated namespace."""
    root=Path(spec['campaign_root']).resolve();out=Path(out).resolve();spec_path=Path(spec_path).resolve()
    if out!=(root/'jobs'/spec['job_id']/'attempts/attempt_001').resolve():raise ValueError('Recovery attempt path mismatch')
    check_never_started(out)
    auth=json.loads(Path(authorization_path).read_text())
    if auth.get('version')=='bc-v3-never-started-recovery-batch-v1':
        entries=[row for row in auth.get('entries',[]) if row.get('job_id')==spec['job_id']]
        if len(entries)!=1:raise ValueError('Recovery batch must identify this job exactly once')
        auth={**auth,**entries[0],'version':'bc-v3-never-started-recovery-v1'}
    if auth.get('version')!='bc-v3-never-started-recovery-v1' or auth.get('job_id')!=spec['job_id'] or Path(auth.get('attempt_path','/missing')).resolve()!=out:
        raise ValueError('Explicit recovery authorization mismatch')
    claim_path=root/'jobs'/spec['job_id']/'claim/owner.json';slot_path=Path(spec['slot_path'])/'owner.json'
    for label,path in [('spec',spec_path),('claim_owner',claim_path),('slot_owner',slot_path)]:
        if sha(path)!=auth.get(label+'_sha256'):raise ValueError('Recovery '+label+' hash differs')
    owner=json.loads(claim_path.read_text());slot=json.loads(slot_path.read_text())
    if (owner.get('job_id')!=spec['job_id'] or owner.get('controller_id')!=spec['controller_id']
        or owner.get('slot')!=spec['slot_path'] or slot.get('job_id')!=spec['job_id']
        or slot.get('controller_id')!=spec['controller_id']):raise ValueError('Recovery ownership differs')
    evidence_path=Path(auth.get('terminated_namespace_evidence_path','/missing'))
    if not evidence_path.is_absolute() or sha(evidence_path)!=auth.get('terminated_namespace_evidence_sha256'):
        raise ValueError('Terminated namespace evidence hash differs')
    evidence=json.loads(evidence_path.read_text())
    if (evidence.get('schema')!='acp-terminated-namespace-v1' or evidence.get('platform_state')!='FAILED'
            or evidence.get('namespace_terminated') is not True):
        raise ValueError('Cloud namespace termination not established')
    for key in ('hostname','boot_id','pid_namespace'):
        if not owner.get(key) or evidence.get(key)!=owner[key]:raise ValueError('Recovery namespace identity mismatch')
    artifacts={}
    for kind in ('describe','bootstrap','exit'):
        path=Path(evidence.get(kind+'_path','/missing'))
        if not path.is_absolute() or sha(path)!=evidence.get(kind+'_sha256'):
            raise ValueError('Recovery '+kind+' evidence hash differs')
        artifacts[kind]=json.loads(path.read_text())
    describe=artifacts['describe'];bootstrap=artifacts['bootstrap'];exit_record=artifacts['exit']
    if (describe.get('workspace_name')!='rl' or describe.get('state')!='FAILED'
            or not describe.get('uid') or describe.get('uid')!=evidence.get('uid')
            or describe.get('name')!=evidence.get('name')
            or not owner['hostname'].startswith('pt-'+describe['uid']+'-')):
        raise ValueError('Official ACP FAILED identity mismatch')
    if any(bootstrap.get(k)!=owner[k] for k in ('hostname','boot_id','pid_namespace')):
        raise ValueError('Bootstrap namespace differs from original claim')
    started=bootstrap.get('started_at_unix');finished=exit_record.get('finished_at_unix')
    if (exit_record.get('controller_exit_code')!=1 or not isinstance(started,(int,float))
            or not isinstance(finished,(int,float)) or finished<started):
        raise ValueError('Failed startup exit must follow this bootstrap')
    if Path(evidence['exit_path']).resolve().parent!=Path(evidence['bootstrap_path']).resolve().parent:
        raise ValueError('Exit and bootstrap must belong to same node/cell')
    return {'authorization_path':str(Path(authorization_path).resolve()),'authorization_sha256':sha(authorization_path),
            'terminated_namespace_evidence_path':str(evidence_path),'terminated_namespace_evidence_sha256':sha(evidence_path),
            'job_id':spec['job_id'],'preserved_spec_sha256':sha(spec_path),'preserved_claim_owner_sha256':sha(claim_path),
            'preserved_slot_owner_sha256':sha(slot_path),'resume_boundary':'Only before original exclusive worker-started guard; no paid/native attempt is replayed'}
