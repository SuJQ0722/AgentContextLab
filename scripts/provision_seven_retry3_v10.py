"""Independent V10 8c32g CCI launch; fixed16, maximum3 attempts including first."""
import argparse
import copy
import json
from pathlib import Path
import shlex
import yaml
from lab import ROOT
from bc_route_runtime_v1 import immutable_json
from run_bc_campaign_v3 import digest
from bootstrap_seven_retry3_v10 import load_validate
import provision_mmbc_cci_v1 as cloud

CAMPAIGN=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/seven-page-retry3-v10'
RECEIPTS=ROOT/'outputs/cloud-runtime/seven-retry3-v10'
TEMPLATES={
 'toolcall-server':ROOT/'outputs/cloud-runtime/visual-inline-two-hour-v7-toolcall-mmbc-v2/acl-vinline-v7-tm-mmbc-vera/config.yaml',
 'agents':cloud.TEMPLATE,
}
CELLS=('bc_hermes','bc_dsh','shared_baselines','mmbc_vera','mmbc_vanilla',*('rq3_scale_'+s for s in ('0000','0250','0500','0700','0750','0800','1000')))
VERSION='visual-inline-seven-page-retry3-v10'



def validated_template(template):
    value=copy.deepcopy(yaml.safe_load(Path(template).read_text()))
    containers=value.get('template',{}).get('containers',[])
    if value.get('replicas')!=1 or len(containers)!=1:
        raise ValueError('Exactly one CCI replica/container required')
    container=containers[0]
    if value['template'].get('resource_spec')!={'name':'N4lS.Iu.I80.8c32g'} or container.get('resource_request')!={'cpu':'8','memory':'32GiB'}:
        raise ValueError('Approved CPU/memory contract differs')
    if container.get('image_path')!='registry.cn-tj-01.sensecore.cn/ccr-zuhu2026/sjq-dev-cpu:sjq-dev-20261108063401' or container.get('env')!=[]:
        raise ValueError('Approved private image/env contract differs')
    mounts=container.get('volume_mounts',[])
    if len(mounts)!=1 or mounts[0].get('mount_path')!='/mnt/afs_agents' or mounts[0].get('id')!='019ed8e0-f4f8-71f7-830c-f8a1e667a9ec' or mounts[0].get('subdir')!='/':
        raise ValueError('afs_agents mount changed')
    return value


def validate_root(cell,root):
    if cell not in CELLS or Path(root).resolve()!=(CAMPAIGN/'cells'/cell).resolve():raise ValueError('Unapproved V10 cell/root')
    plan,manifest=load_validate(root)
    if plan['definition'].get('one_hour_retry_version')!=VERSION:raise ValueError('Wrong campaign')
    return plan,manifest


def prepare(cell,pool):
    if cell not in CELLS or pool not in TEMPLATES:raise ValueError('Invalid cell/pool')
    root=CAMPAIGN/'cells'/cell
    plan,manifest=validate_root(cell,root)
    template=TEMPLATES[pool];value=validated_template(template)
    name='acl-v10s-'+pool+'-'+cell.replace('_','-');directory=RECEIPTS/name;directory.mkdir(parents=True,exist_ok=True)
    marker=directory/'launch-ready.json';container=value['template']['containers'][0]
    if value['resource_pool']['name']!=pool:raise ValueError('Template pool alias mismatch')
    harness='hermes' if plan['definition'].get('container_group')=='shared_baselines' else manifest['harness']
    argv=['/opt/conda/bin/python',str(ROOT/'scripts/bootstrap_seven_retry3_v10.py'),'--root',str(root),'--harness',harness,'--concurrency','16','--reader-python','/opt/conda/bin/python','--live']
    plan_path=root/'plan.json'
    shell='while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 5; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(argv)+'; exec sleep infinity'
    container.update(name='seven-retry3',command=['/bin/bash','-c',shell]);value['display_name']=name
    path=directory/'config.yaml';raw=yaml.safe_dump(value,sort_keys=False).encode()
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Existing launch config differs')
    if not path.exists():path.write_bytes(raw)
    record={'name':name,'cell':cell,'pool':pool,'root':str(root),'plan_sha256':digest(plan_path.read_bytes()),
            'config_path':str(path),'config_sha256':digest(raw),'template_sha256':digest(template.read_bytes()),
            'version':VERSION,'max_attempts':3,'concurrency':16,'cpu':8,'memory_gib':32,
            'provision_source_sha256':digest(Path(__file__).read_bytes()),'launch_marker':str(marker),'automatic_repeat_allowed':False}
    for prior in RECEIPTS.glob('acl-*/request.json'):
        old=json.loads(prior.read_text())
        if old.get('cell')==cell and old.get('name')!=name:raise ValueError('Same cell already submitted elsewhere; explicit migration required')
    immutable_json(directory/'prepared.json',record)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cell',choices=CELLS,required=True);p.add_argument('--pool',choices=TEMPLATES,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--activate',action='store_true');args=p.parse_args()
    record=prepare(args.cell,args.pool)
    if args.live:
        result=cloud.submit(record);print(json.dumps(result),flush=True)
        if result['state']not in('submitted','existing_request_never_repeated'):raise RuntimeError('Creation rejected/unknown; inspect receipt before recovery')
    if args.activate:
        submitted=json.loads((Path(record['config_path']).parent/'response.json').read_text())
        if submitted.get('state')!='submitted' or submitted.get('returncode')!=0:raise ValueError('Creation success unconfirmed; activation forbidden')
        response=cloud.describe(record['name'])
        if response.get('returncode')!=0:raise ValueError('Cannot verify CCI identity before launch')
        value=json.loads(response['stdout'])
        if not value.get('uid') or value.get('name')!=record['name']:raise ValueError('CCI identity differs')
        validate_root(args.cell,Path(record['root']))
        expected=yaml.safe_load(Path(record['config_path']).read_text())
        if len(value.get('template',{}).get('containers',[]))!=1:raise ValueError('Unexpected container count')
        actual_container=value['template']['containers'][0]
        wanted_container=expected['template']['containers'][0]
        if actual_container.get('command')!=wanted_container['command'] or actual_container.get('image_path')!=wanted_container['image_path'] or value.get('resource_pool',{}).get('name')!=expected['resource_pool']['name']:
            raise ValueError('Cloud command/image/pool differs from reviewed launch config')
        for key in ('resource_request','env'):
            if actual_container.get(key)!=wanted_container.get(key):raise ValueError('Resource/environment differs')
        actual_mounts=actual_container.get('volume_mounts',[]);wanted_mounts=wanted_container['volume_mounts']
        if len(actual_mounts)!=1:raise ValueError('AFS mount count differs')
        for key in ('id','mount_path','subdir','zone','type'):
            if actual_mounts[0].get(key)!=wanted_mounts[0].get(key):raise ValueError('AFS mount differs')
        immutable_json(Path(record['config_path']).parent/'binding.json',{'name':record['name'],'uid':value['uid'],'plan_sha256':record['plan_sha256'],'config_sha256':record['config_sha256']})
        immutable_json(Path(record['launch_marker']),{'name':record['name'],'uid':value['uid'],'plan_sha256':record['plan_sha256'],'model_calls_before_marker':0})
    print(json.dumps(record))


if __name__=='__main__':main()
