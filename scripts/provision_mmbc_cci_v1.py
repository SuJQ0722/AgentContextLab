#!/usr/bin/env python3
"""Prepare/submit separate8c32 CCI allocations, each fixed to one MMBC method16.

Default preview is offline. --live alone permits creation after frozen campaign
validation; publication of the launch marker is a separate main-operator action.
"""
import argparse,copy,json,shlex,time
from pathlib import Path
import yaml
from lab import ROOT
from run_bc_campaign_v3 import atomic,digest
from bc_route_runtime_v1 import immutable_json
from replace_sco_bc_v3_after_reader_ops import create_cli,error_reason
from run_mmbc100_campaign import DEFAULT_ROOT,METHODS

TEMPLATE=ROOT/'outputs/cloud-runtime/rq3-resume-ops5/cci7/config.yaml'
RECEIPTS=ROOT/'outputs/cloud-runtime/mmbc100-hermes-cci-v1'
MARKER=RECEIPTS/'launch-ready.json'
PREFIX='acl-mmbc100-hermes-v1-'

def app_name(method):
    if method not in METHODS:raise ValueError('Unreviewed MMBC method; vanilla remains pending')
    return PREFIX+method.replace('_','-')

def build_config(template,method,root=DEFAULT_ROOT,marker=MARKER):
    app_name(method);c=copy.deepcopy(template)
    expected_pool={'name':'agents','available_zone':'cn-tj-01a','vpc_id':'019e25be-ec63-7831-98f8-3993ee8be3ab'}
    if c.get('resource_pool')!=expected_pool or c.get('replicas')!=1:raise ValueError('Reviewed pool/replica contract differs')
    t=c['template'];containers=t['containers']
    if len(containers)!=1 or t['resource_spec']!={'name':'N4lS.Iu.I80.8c32g'}:raise ValueError('Reviewed CPU-only8c32 specification differs')
    x=containers[0]
    if x['image_path']!='registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401' or x['resource_request']!={'cpu':'8','memory':'32GiB'} or x.get('env')!=[]:raise ValueError('Image/resource/env contract differs')
    mount=x['volume_mounts']
    if len(mount)!=1 or mount[0].get('id')!='019ed8e0-f4f8-71f7-830c-f8a1e667a9ec' or mount[0].get('mount_path')!='/mnt/afs_agents' or mount[0].get('subdir')!='/':raise ValueError('Reviewed AFS mount differs')
    if c['scheduling'].get('priority')!='NORMAL' or c['scheduling'].get('quota_type')!='RESERVED':raise ValueError('Priority/quota changed')
    command=['/opt/conda/bin/python',str(ROOT/'scripts/bootstrap_mmbc100_cci.py'),'--root',str(Path(root).resolve()),'--strategy',method,'--concurrency','16','--reader-python','/opt/conda/bin/python','--live']
    # Explicit argv avoids the original CCI command-as-one-string entrypoint bug.
    shell='while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 5; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(command)+'; exec sleep infinity'
    c['display_name']=app_name(method);x['name']='mmbc';x['command']=['/bin/bash','-c',shell]
    return c

def prepare(methods,root=DEFAULT_ROOT,receipts=RECEIPTS):
    from prepare_mmbc100_campaign import load_validate
    root=Path(root).resolve();plan,manifest=load_validate(root)
    if len(set(methods))!=len(methods) or not methods:raise ValueError('Methods must be unique and nonempty')
    template=yaml.safe_load(TEMPLATE.read_text());rows=[]
    for method in methods:
        config=build_config(template,method,root,receipts/'launch-ready.json');raw=yaml.safe_dump(config,sort_keys=False).encode();directory=receipts/app_name(method);directory.mkdir(parents=True,exist_ok=True);path=directory/'config.yaml'
        if path.exists():
            if path.read_bytes()!=raw:raise ValueError('Prepared CCI config changed; use explicit new deployment')
        else:
            with path.open('xb')as f:f.write(raw)
        record={'name':app_name(method),'method':method,'root':str(root),'plan_sha256':digest((root/'plan.json').read_bytes()),'config_path':str(path),'config_sha256':digest(raw),'template_sha256':digest(TEMPLATE.read_bytes()),'bootstrap_sha256':digest((ROOT/'scripts/bootstrap_mmbc100_cci.py').read_bytes()),'controller_sha256':digest((ROOT/'scripts/run_mmbc100_campaign.py').read_bytes()),'launcher_sha256':digest(Path(__file__).read_bytes()),'concurrency':16,'cpu':8,'memory_gib':32,'pool':'agents','launch_marker':str(receipts/'launch-ready.json'),'automatic_repeat_allowed':False}
        if (directory/'prepared.json').exists():
            if json.loads((directory/'prepared.json').read_text())!=record:raise ValueError('Prepared inputs changed')
        else:immutable_json(directory/'prepared.json',record)
        rows.append(record)
    return rows

def describe(name,invoke=create_cli):
    return invoke([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','describe',name,'--workspace-name','rl','--profile','agentcontextlab-tj','-o','json'])

def submit(record,invoke=create_cli):
    directory=Path(record['config_path']).parent
    if (directory/'request.json').exists():return {'name':record['name'],'state':'existing_request_never_repeated'}
    check=describe(record['name'],invoke)
    if check.get('returncode')==0 or not error_reason(check,'appNotFound'):raise ValueError('Fixed application absence not established')
    if digest(Path(record['config_path']).read_bytes())!=record['config_sha256']:raise ValueError('Prepared config changed')
    argv=[str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','create',record['name'],'--workspace-name','rl','--profile','agentcontextlab-tj','--config',record['config_path']]
    immutable_json(directory/'request.json',{**record,'argv':argv,'at':time.time(),'operation':'create','native_calls_before_launch_marker':0})
    response=invoke(argv);state='submitted'if response.get('returncode')==0 else'unknown'if response.get('returncode')is None else'rejected'
    atomic(directory/'response.json',{**response,'state':state,'at':time.time()})
    return {'name':record['name'],'state':state,'receipt':str(directory)}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--methods',nargs='+',choices=METHODS,default=list(METHODS));p.add_argument('--prepare',action='store_true');p.add_argument('--live',action='store_true');p.add_argument('--status',action='store_true');a=p.parse_args()
    if len(a.methods)!=len(set(a.methods)):p.error('Duplicate method')
    if a.status:
        if a.live:p.error('Status cannot create')
        for method in a.methods:
            name=app_name(method);x=describe(name)
            if x.get('returncode')==0:
                d=json.loads(x['stdout']);row={k:d.get(k)for k in ('name','uid','state','ready_replicas')}
            else:row={'name':name,'state':'absent'if error_reason(x,'appNotFound')else'query_unknown'}
            directory=RECEIPTS/name
            if directory.exists():atomic(directory/'status-latest.json',{'at':time.time(),**row})
            print(json.dumps(row))
        return
    if not(a.prepare or a.live):
        template=yaml.safe_load(TEMPLATE.read_text())
        for method in a.methods:build_config(template,method)
        print(json.dumps({'live':False,'methods':a.methods,'cci_count':len(a.methods),'cpu_total':8*len(a.methods),'memory_gib_total':32*len(a.methods),'workers_per_method':16,'model_calls':0,'cloud_api_calls':0,'launch_marker_published':False}));return
    rows=prepare(a.methods)
    if not a.live:print(json.dumps({'prepared':len(rows),'model_calls':0,'cloud_api_calls':0}));return
    for record in rows:
        state=submit(record);print(json.dumps(state),flush=True)
        if state['state']not in ('submitted','existing_request_never_repeated'):raise RuntimeError('Inspect unknown/rejected submission; do not replay')
if __name__=='__main__':main()
