"""Read-only exploratory imputation; never replaces measured result rows."""
import argparse,collections,datetime,hashlib,json
from pathlib import Path
import numpy as np

def main():
 p=argparse.ArgumentParser();p.add_argument('--current',type=Path,required=True);p.add_argument('--historical',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 current=json.loads(a.current.read_text());old=json.loads(a.historical.read_text())
 def key(r):return r['benchmark'],r['model'],r['harness'],r['method'],r['question_hash'],r['repeat']
 history={key(r):r for r in old}; groups=collections.defaultdict(list)
 for r in current:
  if r['benchmark']=='bc100':groups[(r['model'],r['harness'])].append(r)
 out={'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'input_sha256':{str(x):hashlib.sha256(x.read_bytes()).hexdigest()for x in (a.current,a.historical)},'model_calls':0,'groups':[]}
 methods=['none','discard','sliding_window','summarize']
 for family,rs in sorted(groups.items()):
  ix={m:{(r['question_hash'],r['repeat']):r for r in rs if r['method']==m}for m in methods+['visual']};v=ix['visual'];assert len(v)==300
  S={k for k,r in v.items()if r['status']=='completed'and r.get('score')in(0,1)}
  Z={k for k,r in v.items()if r.get('classification')=='budget_exhausted_zero'}
  T={k for k,r in v.items()if k not in S|Z and (r.get('timeout')or history.get(key(r),{}).get('timeout'))}
  U=set(v)-S-Z-T
  basevalid=set.intersection(*[{k for k,r in ix[m].items()if r.get('score')in(0,1)}for m in methods]);ss=S&basevalid;tt=T&basevalid
  def avg(m,ks):return float(np.mean([ix[m][k]['score']for k in ks]))if ks else None
  g={'model':family[0],'harness':family[1],'vera_scored_completed':len(S),'historical_timeout_unresolved':len(T),'current_status_timeout':sum(r['status']=='timeout'for r in v.values()),'explicit_budget_zero':len(Z),'other_unknown':len(U),'common_S':len(ss),'common_T':len(tt),'repeat_common_S':[sum(k[1]==j for k in ss)for j in (1,2,3)],'repeat_common_T':[sum(k[1]==j for k in tt)for j in (1,2,3)],'baseline_comparison':[]}
  for m in methods:
   ks={k for k,r in ix[m].items()if r.get('score')in(0,1)};ps=avg(m,ss);pt=avg(m,tt)
   g['baseline_comparison'].append({'method':m,'common_S_accuracy':ps,'common_T_accuracy':pt,'ratio':pt/ps if ps and pt is not None else None,'difference':pt-ps if ps is not None and pt is not None else None,'own_S_n':len(S&ks),'own_T_n':len(T&ks),'own_S_accuracy':avg(m,S&ks),'own_T_accuracy':avg(m,T&ks)})
  if ss and tt:
   sp=np.array([avg(m,ss)for m in methods]);tp=np.array([avg(m,tt)for m in methods]);k=float(tp.mean()/sp.mean());vs=avg('visual',ss);pred=float(np.clip(vs*k,0,1));add=float(np.clip(vs+tp.mean()-sp.mean(),0,1));correct=sum(v[x]['score']for x in S)
   def total(p):return[(correct+len(T)*p)/300,(correct+len(T)*p+len(U))/300]
   g.update(vera_S_all_accuracy=avg('visual',S),vera_S_common_accuracy=vs,pooled_baseline_ratio=k,imputed_timeout_accuracy=pred,imputed_full300_range=total(pred),additive_timeout_accuracy=add,additive_full300_range=total(add),per_baseline_timeout_predictions=[float(np.clip(vs*x/y,0,1))for x,y in zip(tp,sp)],leave_one_baseline_out_errors=[])
   for j,m in enumerate(methods):
    kk=float(np.delete(tp,j).mean()/np.delete(sp,j).mean());pr=float(np.clip(sp[j]*kk,0,1));g['leave_one_baseline_out_errors'].append({'method':m,'predicted_T_accuracy':pr,'observed_T_accuracy':float(tp[j]),'error_pp':100*(pr-tp[j])})
   # Resample question clusters, preserving repeat membership and availability masks.
   qs=sorted({x[0]for x in v}); qi={x:j for j,x in enumerate(qs)};arr=np.zeros((len(qs),6))
   for x in ss:
    arr[qi[x[0]],0]+=1;arr[qi[x[0]],1]+=sum(ix[m][x]['score']for m in methods)/4;arr[qi[x[0]],2]+=v[x]['score']
   for x in tt:
    arr[qi[x[0]],3]+=1;arr[qi[x[0]],4]+=sum(ix[m][x]['score']for m in methods)/4
   rng=np.random.default_rng(20261113);dist=[]
   for batch in range(20):
    z=arr[rng.integers(0,len(qs),size=(500,len(qs)))].sum(axis=1);ok=(z[:,0]>0)&(z[:,3]>0)&(z[:,1]>0);z=z[ok];dist.extend(np.clip(z[:,2]/z[:,0]*(z[:,4]/z[:,3])/(z[:,1]/z[:,0]),0,1).tolist())
   g['imputed_timeout_cluster_bootstrap95_conditional']=np.quantile(dist,[.025,.975]).tolist();g['imputed_full300_baseline_specific_range']=[min(total(x)[0]for x in g['per_baseline_timeout_predictions']),max(total(x)[1]for x in g['per_baseline_timeout_predictions'])]
  else:g['projection_unavailable_reason']='No explicitly documented unresolved timeout subset; missing/failed records are not assumed to be timeouts.'
  out['groups'].append(g)
 a.out.mkdir(parents=True,exist_ok=True);(a.out/'bc-timeout-transfer.json').write_text(json.dumps(out,ensure_ascii=False,indent=2));print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
