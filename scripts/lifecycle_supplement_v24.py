"""Stop only this campaign's bound CCIs after every owned child is cleanly terminal."""
import argparse,json,time
from pathlib import Path
from lab import ROOT
from supplement_recovery_v24 import DEFAULT,read,save,immutable
from provision_supplement_v24 import OUT
from provision_mmbc_cci_v1 import describe
from replace_sco_bc_v3_after_reader_ops import create_cli

def cycle(live=False):
    plan=read(DEFAULT/'plan.json');rows=[]
    for scope in ('core','controlled'):
        for shard in range(3):
            name=f'acl-supp24-{scope}-{shard}';folder=OUT/name
            status=DEFAULT/'runtime'/scope/str(shard)/'status.json'
            state=read(status)if status.exists()else{}
            jobs=[j for j in plan['jobs']if j['scope']==scope and j['shard']==shard]
            clean=state.get('finished')is True and state.get('active')==state.get('pending')==0 and not state.get('unknown')
            if clean:
                for job in jobs:
                    result=read(DEFAULT/'jobs'/job['job_id']/'attempts/attempt_001/result.json')
                    if result.get('slot_released')is not True:clean=False;break
            row={'name':name,'drained':clean,'stop_requested':(folder/'stop-request.json').exists()};rows.append(row)
            if clean and live and not row['stop_requested']:
                value=describe(name)
                if value.get('returncode')!=0:continue
                actual=json.loads(value['stdout']);binding=read(folder/'binding.json')
                if actual.get('uid')!=binding['uid'] or actual.get('name')!=name:raise ValueError('Cloud UID changed; refuse stop')
                if actual.get('state')not in ('RUNNING','PROGRESSING'):continue
                immutable(folder/'stop-request.json',{'at':time.time(),'name':name,'uid':binding['uid'],'all_tasks_terminal_cleanup_confirmed':True})
                response=create_cli([str(ROOT/'.tools/sco-tj/cli/sco'),'cci','apps','stop',name,'--workspace-name','rl','--profile','agentcontextlab-tj'])
                save(folder/'stop-response.json',response);row['stop_requested']=True
    save(OUT/'lifecycle-status.json',{'at':time.time(),'rows':rows,'automatic_stop_replay':False})
    return all(x['stop_requested']for x in rows)

def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');p.add_argument('--live',action='store_true');a=p.parse_args()
    while True:
        done=cycle(a.live)
        if done or not a.watch:break
        time.sleep(30)
if __name__=='__main__':main()
