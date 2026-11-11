"""Move approved never-started V7 allocations to the compatible agentic-rl pool; immutable attempts remain intact."""
import argparse
import copy
import json
from pathlib import Path
import time
import yaml
from lab import ROOT
from prepare_mmbc100_campaign import immutable_json,sha
from bootstrap_visual_inline_two_hour_v7 import DEFAULT_ROOT,load_validate
import provision_visual_inline_two_hour_v7 as original
import repool_visual_inline_mmbc_toolcall_v7 as vanilla_previous
import repool_visual_inline_toolcall_pool_v7 as controlled_previous
import provision_mmbc_cci_v1 as cli

CELLS=('controlled_mmbc','mmbc_vanilla',*('rq3_scale_'+s for s in ('0000','0250','0500','0700','0750','0800','1000')))
RECEIPTS=ROOT/'outputs/cloud-runtime/visual-inline-two-hour-v7-agentic-v1'

def app_name(cell):
    if cell not in CELLS:raise ValueError('Unapproved migration cell')
    return 'acl-vinline-v7-ar-'+cell.replace('_','-')

def read(path):return json.loads(Path(path).read_text())

def no_execution(root):
    root=Path(root);patterns=('runtime/nodes/*/*/bootstrap.json','controllers/*/*/maintenance.json',
        'controllers/*/*/status.json','jobs/*/*/*/claim/owner.json','cells/*/*/slots/*/owner.json',
        'jobs/*/*/*/attempts/*/worker-started.json','jobs/*/*/*/attempts/*/running.json',
        'jobs/*/*/*/attempts/*/controller-dispatched.json','jobs/*/*/*/attempts/*/native/attempt-started.json',
        'jobs/*/*/*/attempts/*/result.json','jobs/*/*/*/attempts/*/native/native-result.json')
    found=[str(p.relative_to(root))for pattern in patterns for p in root.glob(pattern)]
    if found:raise ValueError('Execution evidence exists; natural drain required: '+','.join(found[:4]))
    return {'at_unix':time.time(),'no_execution_evidence':True,'patterns':list(patterns)}

def config_matches(app,config):
    expected=config['template']['containers'];actual=app.get('template',{}).get('containers',[])
    if len(expected)!=1 or len(actual)!=1:raise ValueError('Unexpected sidecar/container count')
    a,b=actual[0],expected[0]
    for key in ('command','image_path','resource_request','env'):
        if a.get(key)!=b.get(key):raise ValueError('Platform executable/resource config differs: '+key)
    am,bm=a.get('volume_mounts',[]),b.get('volume_mounts',[])
    if len(am)!=len(bm):raise ValueError('Volume count differs')
    for x,y in zip(am,bm):
        for key in ('id','mount_path','subdir','type','zone'):
            if x.get(key)!=y.get(key):raise ValueError('Platform AFS mount differs')
    if app.get('resource_pool',{}).get('name')!=config['resource_pool']['name']:raise ValueError('Pool differs')

def fresh(record):
    response=cli.describe(record['old_name'])
    if response.get('returncode')!=0:raise ValueError('Old application query failed')
    app=json.loads(response['stdout'])
    if app.get('uid')!=record['old_uid'] or app.get('name')!=record['old_name']:raise ValueError('Old UID differs')
    if sha(record['old_config_path'])!=record['old_config_sha256']:raise ValueError('Old config SHA differs')
    config_matches(app,yaml.safe_load(Path(record['old_config_path']).read_text()))
    return app

def prepare(cell):
    app_name(cell);source=controlled_previous if cell=='controlled_mmbc' else vanilla_previous if cell=='mmbc_vanilla' else original
    old=read(source.RECEIPTS/source.app_name(cell)/'prepared.json')
    root=Path(old['root']);load_validate(root);no_execution(root)
    response=cli.describe(old['name'])
    if response.get('returncode')!=0:raise ValueError('Cannot bind original UID')
    actual=json.loads(response['stdout']);config=yaml.safe_load(Path(old['config_path']).read_text());new=copy.deepcopy(config)
    name=app_name(cell);directory=RECEIPTS/name;marker=RECEIPTS/'markers'/(cell+'.json')
    if marker.exists() or (directory/'request.json').exists():raise ValueError('New deployment already attempted/marked')
    new['display_name']=name;new['resource_pool']['name']='agentic-rl'
    new['template']['containers'][0]['command'][-1]=new['template']['containers'][0]['command'][-1].replace(old['launch_marker'],str(marker))
    check=copy.deepcopy(new);check['display_name']=config['display_name'];check['resource_pool']['name']=config['resource_pool']['name']
    check['template']['containers'][0]['command'][-1]=check['template']['containers'][0]['command'][-1].replace(str(marker),old['launch_marker'])
    if check!=config:raise ValueError('Unapproved config difference')
    raw=yaml.safe_dump(new,sort_keys=False);directory.mkdir(parents=True,exist_ok=True);path=directory/'config.yaml'
    if path.exists() and path.read_text()!=raw:raise ValueError('Migration config changed')
    if not path.exists():path.write_text(raw)
    record={**old,'name':name,'config_path':str(path),'config_sha256':sha(path),'launch_marker':str(marker),
       'old_name':old['name'],'old_uid':actual['uid'],'old_config_path':old['config_path'],
       'old_config_sha256':old['config_sha256'],'pool':'agentic-rl','migration_source_sha256':sha(__file__),
       'approved_diff':['display_name','resource_pool.name','launch_marker_in_command']}
    existing=directory/'prepared.json'
    if existing.exists():
        if read(existing)!=record:raise ValueError('Migration binding changed')
    else:immutable_json(existing,record)
    fresh(record);return record

def migrate(record):
    directory=Path(record['config_path']).parent;root=Path(record['root'])
    load_validate(root)
    if Path(record['launch_marker']).exists() or (directory/'request.json').exists():raise ValueError('New allocation already attempted/marked')
    if sha(record['old_config_path'])!=record['old_config_sha256'] or sha(record['config_path'])!=record['config_sha256']:raise ValueError('Configuration binding differs')
    if sha(__file__)!=record['migration_source_sha256'] or sha(root/'plan.json')!=record['plan_sha256']:raise ValueError('Frozen migration binding differs')
    if (directory/'old-stop-request.json').exists():raise ValueError('Migration already attempted; manual review required')
    before=fresh(record);evidence=no_execution(root)
    if before.get('state') not in ('PROGRESSING','CREATING') or before.get('ready_replicas')!=0:raise ValueError('Original allocation not pending zero-ready')
    guard={'reason':'root-approved never-started allocation migration','old_uid':record['old_uid'],'at_unix':time.time()}
    immutable_json(root/'STOP',guard)
    # This dispatch guard closes the pending-pod start race before the stop request.
    no_execution(root);fresh(record)
    immutable_json(directory/'old-stop-request.json',{'at_unix':time.time(),'old_uid':record['old_uid'],'before':evidence})
    response=cli.create_cli([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','stop',record['old_name'],'--workspace-name','rl','--profile','agentcontextlab-tj'])
    immutable_json(directory/'old-stop-response.json',response)
    if response.get('returncode')!=0:raise ValueError('Old stop unconfirmed; never retry blindly')
    for unused in range(60):
        after=fresh(record)
        if after.get('state') in ('SUSPENDED','STOPPED') and after.get('ready_replicas')==0:break
        time.sleep(2)
    else:raise ValueError('Original allocation stop not confirmed')
    after_evidence=no_execution(root)
    immutable_json(directory/'old-stopped-proof.json',{'at_unix':time.time(),'old_uid':record['old_uid'],'state':after['state'],'ready_replicas':0,'execution':after_evidence})
    if read(root/'STOP')!=guard:raise ValueError('Dispatch guard changed')
    (root/'STOP').unlink()
    result=cli.submit(record)
    if result['state']!='submitted':raise ValueError('New create unconfirmed; never repeat')
    check=cli.describe(record['name'])
    if check.get('returncode')!=0:raise ValueError('New allocation identity unavailable; marker stays absent')
    new=json.loads(check['stdout'])
    if new.get('name')!=record['name'] or not new.get('uid') or new['uid']==record['old_uid']:raise ValueError('New allocation identity invalid')
    config_matches(new,yaml.safe_load(Path(record['config_path']).read_text()))
    immutable_json(directory/'new-binding.json',{'name':new['name'],'uid':new['uid'],'old_uid':record['old_uid'],'plan_sha256':record['plan_sha256'],'config_sha256':record['config_sha256']})
    immutable_json(record['launch_marker'],{'authorized_by':'root_review','at_unix':time.time(),'plan_sha256':record['plan_sha256'],
       'config_sha256':record['config_sha256'],'old_uid':record['old_uid'],'timeout_seconds':7200,'concurrency':16})
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cells',choices=CELLS,nargs='+',required=True);p.add_argument('--live',action='store_true');a=p.parse_args()
    if len(set(a.cells))!=len(a.cells):p.error('Duplicate cells')
    for cell in a.cells:
        record=prepare(cell)
        print(json.dumps(migrate(record)if a.live else {'cell':cell,'prepared':True,'live':False,'config_sha256':record['config_sha256']}),flush=True)

if __name__=='__main__':main()
