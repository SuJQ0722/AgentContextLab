"""Six isolated CCI allocations; create receipts and bound activation are separate."""
import argparse,json,shlex,time
from pathlib import Path
import yaml
from lab import ROOT
from supplement_recovery_v24 import DEFAULT,immutable,read,sha,validate_plan
from provision_controlled_source_v20 import template_value,bind
import provision_mmbc_cci_v1 as cloud

OUT=ROOT/'outputs/cloud-runtime/supplement-timeout-v24'
def prepare(scope,shard,root=DEFAULT):
    name=f'acl-supp24-{scope}-{shard}';folder=OUT/name;folder.mkdir(parents=True,exist_ok=True)
    marker=folder/'launch-ready.json';config=template_value();config['display_name']=name
    config['resource_pool']['name']='design'
    command=['/opt/conda/bin/python',str(ROOT/'scripts/network_entry_v13.py'),'--target',str(ROOT/'scripts/supplement_recovery_v24.py'),'run','--root',str(root),'--scope',scope,'--shard',str(shard)]
    shell='while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 3; done; cd '+shlex.quote(str(ROOT))+' && '+shlex.join(command)+'; exec sleep infinity'
    config['template']['containers'][0].update(name=f'supp24-{scope}-{shard}',command=['/bin/bash','-c',shell])
    path=folder/'config.yaml';raw=yaml.safe_dump(config,sort_keys=False).encode()
    if path.exists() and path.read_bytes()!=raw:raise ValueError('Cloud definition changed')
    path.write_bytes(raw)
    record={'name':name,'scope':scope,'shard':shard,'root':str(root),'pool':'design','config_path':str(path),
            'config_sha256':sha(path),'plan_sha256':sha(root/'plan.json'),'launch_marker':str(marker),
            'concurrency':8,'cpu':8,'memory_gib':32,'automatic_create_replay':False}
    immutable(folder/'prepared.json',record);return record

def main():
    p=argparse.ArgumentParser();p.add_argument('--create',action='store_true');p.add_argument('--activate',action='store_true');p.add_argument('--scope',choices=['core','controlled'],required=True);p.add_argument('--shard',type=int,choices=range(3),required=True)
    a=p.parse_args();validate_plan(DEFAULT,True);r=prepare(a.scope,a.shard)
    if a.create:
        response=cloud.submit(r)
        if response['state']not in ('submitted','existing_request_never_repeated'):raise RuntimeError('Cloud create unconfirmed; no automatic replay')
        receipt=read(Path(r['config_path']).parent/'response.json')
        if receipt.get('state')!='submitted' or receipt.get('returncode')!=0:raise RuntimeError('Unconfirmed cloud create')
        value=bind(r)
        if a.activate:immutable(r['launch_marker'],{'at':time.time(),'uid':value['uid'],'plan_sha256':r['plan_sha256'],'concurrency':8})
        print(json.dumps({'name':r['name'],'state':value['state'],'activated':a.activate}))
    else:
        if a.activate:raise ValueError('Activation requires creation receipt')
        print(json.dumps({'name':r['name'],'model_calls':0,'cloud_mutations':0}))
if __name__=='__main__':main()
