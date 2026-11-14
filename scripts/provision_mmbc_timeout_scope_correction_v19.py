"""Two isolated normal-priority 8c32g/16-slot CCIs; immutable request receipts."""
import argparse,concurrent.futures,hashlib,json,shlex,sys,time,re
from pathlib import Path
import yaml
R=Path('/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab');sys.path.insert(0,str(R/'scripts'));from provision_controlled_source_v17 import template_value;import provision_mmbc_cci_v1 as cloud
from bc_route_runtime_v1 import immutable_json
from prepare_visual_hosted_retry_v1 import load_validate
from recovery_once_contract_v19 import VERSION,validate_turns,validate_authorization,dispatch_allowed
ROOT=R/'outputs/campaigns/mmbc-timeout-scope-correction-v19';OUT=R/'outputs/cloud-runtime/mmbc-timeout-scope-correction-v19';ENTRY=R/'scripts/network_entry_v13.py';ONCE=R/'scripts/recovery_once_entry_v19.py';BOOT=R/'scripts/bootstrap_recovery_once_v19.py'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def app_name(cell):return 'acl-mmbc-retry19-'+re.sub('[^a-z0-9-]','-',cell.lower())
def prepare(item,pool='design'):
 root=Path(item['root']);assert root.parent==ROOT/'cells';assert not root.name.startswith('sample_');plan,m=load_validate(root);assert plan['definition']['one_pass_version']==VERSION and len(plan['jobs'])<=59;assert len({j['harness']for j in plan['jobs']})==1
 for j in plan['jobs']:validate_turns(j,read(j['config_path']));validate_authorization({**j,'campaign_root':str(root)})
 name=app_name(item['cell']);assert len(name)<=63;d=OUT/'apps'/name;d.mkdir(parents=True,exist_ok=True);marker=d/'launch-ready.json';v=template_value();v['resource_pool']['name']=pool;v['display_name']=name;h=plan['jobs'][0]['harness']
 argv=['/opt/conda/bin/python',str(ENTRY),'--target',str(ONCE),'--target',str(BOOT),'--root',str(root),'--harness',h,'--concurrency','16','--reader-python','/opt/conda/bin/python','--live']
 shell='while [ ! -f '+shlex.quote(str(marker))+' ]; do sleep 3; done; cd '+shlex.quote(str(R))+' && '+shlex.join(argv)+'; exec sleep infinity';v['template']['containers'][0].update(name='one-pass-shard',command=['/bin/bash','-c',shell]);p=d/'config.yaml';raw=yaml.safe_dump(v,sort_keys=False).encode()
 if p.exists():assert p.read_bytes()==raw
 else:p.write_bytes(raw)
 rec={'name':name,'cell':item['cell'],'root':str(root),'harness':h,'pool':pool,'planned_runs':len(plan['jobs']),'plan_sha256':sha(root/'plan.json'),'config_path':str(p),'config_sha256':sha(p),'launch_marker':str(marker),'runtime_source_sha256':{str(x):sha(x)for x in(ENTRY,ONCE,BOOT)},'cpu':8,'memory_gib':32,'concurrency':16,'one_pass_version':VERSION,'max_new_attempts':1,'no_automatic_create_replay':True,'ops_source_sha256':sha(__file__)};immutable_json(d/'prepared.json',rec);return rec

def launch(rec,activate=False):
 assert dispatch_allowed(time.time()),'Too late for a full one-hour task before hard deadline';load_validate(Path(rec['root']))
 for p,h in rec['runtime_source_sha256'].items():assert sha(p)==h
 res=cloud.submit(rec);d=Path(rec['config_path']).parent
 if res['state']not in('submitted','existing_request_never_repeated'):return res
 receipt=read(d/'response.json');assert receipt.get('state')=='submitted'and receipt.get('returncode')==0
 answer=cloud.describe(rec['name']);assert answer['returncode']==0;v=json.loads(answer['stdout']);want=yaml.safe_load(Path(rec['config_path']).read_text());assert v['name']==rec['name']and v['uid'];assert v['resource_pool']['name']==rec['pool'];assert len(v['template']['containers'])==1
 c=v['template']['containers'][0];e=want['template']['containers'][0]
 for k in('command','image_path','resource_request','env'):assert c[k]==e[k]
 for k in('id','mount_path','subdir'):assert c['volume_mounts'][0][k]==e['volume_mounts'][0][k]
 immutable_json(d/'binding.json',{'uid':v['uid'],'name':v['name'],'plan_sha256':rec['plan_sha256'],'config_sha256':rec['config_sha256']})
 if activate:
  load_validate(Path(rec['root']));immutable_json(Path(rec['launch_marker']),{'at':time.time(),'uid':v['uid'],'name':v['name'],'plan_sha256':rec['plan_sha256'],'runtime_source_sha256':rec['runtime_source_sha256'],'one_pass_version':VERSION})
 return {'cell':rec['cell'],'name':rec['name'],'uid':v['uid'],'platform_state':v['state'],'ready':v.get('ready_replicas'),'activated':activate}

def main():
 p=argparse.ArgumentParser();p.add_argument('--cells',nargs='+');p.add_argument('--pool',default='design',choices=['design','rsi','toolcall-server']);p.add_argument('--create',action='store_true');p.add_argument('--activate',action='store_true');p.add_argument('--workers',type=int,default=4);a=p.parse_args();assert not a.activate or a.create
 items=[read(ROOT/'cells'/c/'campaign-manifest.json')for c in a.cells]if a.cells else read(ROOT/'inventory.json')['cells'];assert items
 def one(i):
  rec=prepare(i,a.pool);return launch(rec,a.activate)if a.create else{'cell':rec['cell'],'name':rec['name'],'prepared':True,'model_calls':0}
 with concurrent.futures.ThreadPoolExecutor(max_workers=a.workers)as ex:
  for result in ex.map(one,items):print(json.dumps(result),flush=True)
if __name__=='__main__':main()
