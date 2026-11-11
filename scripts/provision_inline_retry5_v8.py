"""Versioned 8c32g CCI launch; one visual cell or one shared 16-slot baseline queue."""
import argparse
import copy
import json
from pathlib import Path
import shlex
import yaml
from lab import ROOT
from bc_route_runtime_v1 import immutable_json
from run_bc_campaign_v3 import digest
from prepare_visual_hosted_retry_v1 import load_validate
import provision_mmbc_cci_v1 as cloud

CAMPAIGN=ROOT/'outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v8-one-hour-retry5'
RECEIPTS=ROOT/'outputs/cloud-runtime/inline-retry5-v8'
TEMPLATES={
 'agentic':ROOT/'outputs/cloud-runtime/visual-inline-two-hour-v7-agentic-v1/acl-vinline-v7-ar-mmbc-vanilla/config.yaml',
 'toolcall':ROOT/'outputs/cloud-runtime/visual-inline-two-hour-v7-toolcall-mmbc-v2/acl-vinline-v7-tm-mmbc-vera/config.yaml',
 'agents':cloud.TEMPLATE,
}


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
    if cell=='info_loss':
        from info_loss_inline_retry_v8 import verify
        manifest=json.loads((root/'manifest.json').read_text());verify(root,manifest)
        return None,manifest
    plan,manifest=load_validate(root)
    if plan['definition'].get('one_hour_retry_version')!='visual-inline-one-hour-retry5-v8':raise ValueError('Wrong campaign')
    return plan,manifest


def prepare(cell,pool):
    if not cell or any(x not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for x in cell):raise ValueError('Invalid cell name')
    root=ROOT/'outputs/experiment6/inline-retry5-v8' if cell=='info_loss' else CAMPAIGN/'cells'/cell
    plan,manifest=validate_root(cell,root)
    template=TEMPLATES[pool];value=validated_template(template)
    name='acl-v8-'+pool+'-'+cell.replace('_','-');directory=RECEIPTS/name;directory.mkdir(parents=True,exist_ok=True)
    marker=directory/'launch-ready.json';container=value['template']['containers'][0]
    if cell=='info_loss':
        argv=['/opt/conda/bin/python',str(ROOT/'scripts/info_loss_inline_retry_v8.py'),'--output',str(root),'--resume','--live']
        plan_path=root/'manifest.json'
    else:
        harness='hermes' if plan['definition'].get('container_group')=='shared_baselines' else manifest['harness']
        argv=['/opt/conda/bin/python',str(ROOT/'scripts/bootstrap_visual_inline_retry5_v8.py'),'--root',str(root),'--harness',harness,'--concurrency','16','--reader-python','/opt/conda/bin/python','--live']
        plan_path=root/'plan.json'
    shell='while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 5; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(argv)+'; exec sleep infinity'
    container.update(name='inline-retry5',command=['/bin/bash','-c',shell]);value['display_name']=name
    path=directory/'config.yaml';raw=yaml.safe_dump(value,sort_keys=False).encode()
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Existing launch config differs')
    if not path.exists():path.write_bytes(raw)
    record={'name':name,'cell':cell,'pool':pool,'root':str(root),'plan_sha256':digest(plan_path.read_bytes()),
            'config_path':str(path),'config_sha256':digest(raw),'template_sha256':digest(template.read_bytes()),
            'concurrency':16,'cpu':8,'memory_gib':32,'launch_marker':str(marker),'automatic_repeat_allowed':False}
    immutable_json(directory/'prepared.json',record)
    return record


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cell',required=True);p.add_argument('--pool',choices=TEMPLATES,required=True)
    p.add_argument('--live',action='store_true');p.add_argument('--activate',action='store_true');args=p.parse_args()
    record=prepare(args.cell,args.pool)
    if args.live:
        result=cloud.submit(record);print(json.dumps(result),flush=True)
        if result['state']not in('submitted','existing_request_never_repeated'):raise RuntimeError('Creation rejected/unknown; inspect receipt before recovery')
    if args.activate:
        response=cloud.describe(record['name'])
        if response.get('returncode')!=0:raise ValueError('Cannot verify CCI identity before launch')
        value=json.loads(response['stdout'])
        if not value.get('uid'):raise ValueError('CCI has no identity')
        validate_root(args.cell,Path(record['root']))
        expected=yaml.safe_load(Path(record['config_path']).read_text())
        actual_container=value.get('template',{}).get('containers',[{}])[0]
        wanted_container=expected['template']['containers'][0]
        if actual_container.get('command')!=wanted_container['command'] or actual_container.get('image_path')!=wanted_container['image_path'] or value.get('resource_pool',{}).get('name')!=expected['resource_pool']['name']:
            raise ValueError('Cloud command/image/pool differs from reviewed launch config')
        immutable_json(Path(record['launch_marker']),{'name':record['name'],'uid':value['uid'],'plan_sha256':record['plan_sha256'],'model_calls_before_marker':0})
    print(json.dumps(record))


if __name__=='__main__':main()
