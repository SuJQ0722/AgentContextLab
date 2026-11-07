#!/usr/bin/env python3
"""Rebuild pilot reporting without API calls; missing usage remains unknown."""
import argparse,json,os,time
from collections import defaultdict
from pathlib import Path
from info_loss_eval import ROOT,save,report

def summarize_usage(rows, calls_started):
    """Sum only observed fields; completeness includes unreturned requests.

    A subtotal of zero with zero observed fields is not a measured zero total.
    Input/cache conservation is checked per response, never across populations.
    """
    count=lambda value: isinstance(value,int) and not isinstance(value,bool) and value>=0
    u={'calls_started':calls_started,'calls_returned':len(rows),'missing_usage':0,
       'input_tokens_known':0,'cached_input_tokens_known':0,'output_tokens_known':0,
       'total_tokens_reported_known':0,'total_tokens_derived_known':0,
       'known_noncache_input_tokens':0,'client_http_seconds_known':0,
       'actual_cost_usd':None,'provider_api_seconds':None,'image_tokens':None,
       'conservation_checked_calls':0,'conservation_error_calls':0,
       'cache_conservation_checked_calls':0,'cache_conservation_error_calls':0}
    names={'prompt':'input_tokens_known','output':'output_tokens_known',
           'cached':'cached_input_tokens_known','total':'total_tokens_reported_known',
           'derived_total':'total_tokens_derived_known','noncache':'known_noncache_input_tokens'}
    observed={k:0 for k in names}
    for row in rows:
        usage=row.get('usage')
        if not isinstance(usage,dict) or not usage:u['missing_usage']+=1;usage={}
        details=usage.get('prompt_tokens_details')
        details=details if isinstance(details,dict) else {}
        values={'prompt':usage.get('prompt_tokens'),'output':usage.get('completion_tokens'),
                'cached':details.get('cached_tokens'),'total':usage.get('total_tokens')}
        seconds=row.get('client_http_seconds')
        if isinstance(seconds,(int,float)) and not isinstance(seconds,bool) and seconds>=0:
            u['client_http_seconds_known']+=seconds
        for key,value in values.items():
            if count(value):u[names[key]]+=value;observed[key]+=1
        prompt,output,cached,total=[values[k] for k in ('prompt','output','cached','total')]
        if count(prompt) and count(output):
            observed['derived_total']+=1;u['total_tokens_derived_known']+=prompt+output
            if count(total):
                u['conservation_checked_calls']+=1
                u['conservation_error_calls']+=int(total!=prompt+output)
        if count(prompt) and count(cached):
            u['cache_conservation_checked_calls']+=1
            if cached>prompt:u['cache_conservation_error_calls']+=1
            else:observed['noncache']+=1;u['known_noncache_input_tokens']+=prompt-cached
    pending=max(0,calls_started-len(rows))
    u['usage_in_flight_unknown']=pending
    u['response_count_exceeds_started']=len(rows)>calls_started
    for key,n in observed.items():
        u[key+'_observed_calls']=n
        u[key+'_missing_returned_calls']=len(rows)-n
        u[key+'_unknown_calls']=len(rows)-n+pending
    u['cached_unknown']=u['cached_missing_returned_calls']
    complete=lambda key: bool(calls_started>0 and observed[key]==calls_started and not u['response_count_exceeds_started'])
    u['full_input_tokens']=u['input_tokens_known'] if complete('prompt') else None
    u['full_output_tokens']=u['output_tokens_known'] if complete('output') else None
    u['full_cached_input_tokens']=u['cached_input_tokens_known'] if complete('cached') and not u['cache_conservation_error_calls'] else None
    u['full_noncache_input_tokens']=u['known_noncache_input_tokens'] if complete('noncache') else None
    u['full_total_tokens']=u['total_tokens_reported_known'] if complete('total') and not u['conservation_error_calls'] else None
    u['usage_complete']=bool(complete('prompt') and complete('output') and complete('cached') and complete('total') and not u['conservation_error_calls'] and not u['cache_conservation_error_calls'])
    u['note']='Known subtotals sum observed fields only; different fields may cover different calls. They are not full campaign totals. Missing/null/invalid fields remain unknown. Non-cache and derived total require both operands from the same response.'
    return u

def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');p.add_argument('--output',type=Path,default=ROOT/'outputs/experiment6/real-trajectory-pilot-v2');a=p.parse_args();out=a.output
    if a.watch:
        import subprocess,sys
        while True:
            subprocess.run([sys.executable,__file__,'--output',str(out)],check=True)
            result=json.loads((out/'results.json').read_text()) if (out/'results.json').exists() else {}
            if result.get('status')=='completed':return
            running=json.loads((out/'running.json').read_text())
            try:os.kill(running['pid'],0)
            except ProcessLookupError:return
            time.sleep(30)
    manifest=json.loads((out/'manifest.json').read_text());results=json.loads((out/'results.json').read_text()) if (out/'results.json').exists() else {'status':'running','records':[]}
    rows=[json.loads(path.read_text()) for path in (out/'calls').glob('*/response.json')]
    usage=summarize_usage(rows,len(list((out/'calls').glob('*/started.json'))))
    save(out/'usage-summary.json',usage);report(out,manifest,results['records'])
    with (out/'report.md').open('a') as stream:stream.write('\n## Provider counters (known subtotal)\n\n```json\n'+json.dumps(usage,indent=2)+'\n```\n')
    if results['records']:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        groups=defaultdict(list)
        for row in results['records']:
            if row['method'].startswith('render_') and row['qa_status']=='completed' and row['qa_finish_reason']=='stop':groups[row['sample']].append(row)
        fig,axs=plt.subplots(1,2,figsize=(10,4))
        for sample,rows in groups.items():
            rows.sort(key=lambda r:float(r['method'].split('_')[1]))
            axs[0].plot([float(r['method'].split('_')[1]) for r in rows],[r['qa_exact_correct']/r['fact_count'] for r in rows],marker='o',label=sample)
        for method in sorted(set(r['method'] for r in results['records'])):
            rows=[r for r in results['records'] if r['method']==method and r['distance_steps'] is not None and r['qa_status']=='completed' and r['qa_finish_reason']=='stop']
            if rows:axs[1].scatter([r['distance_steps'] for r in rows],[r['qa_exact_correct']/r['fact_count'] for r in rows],label=method)
        axs[0].set(xlabel='Render scale',ylabel='Exact probe accuracy',ylim=(-.05,1.05),title='One trajectory: descriptive only')
        axs[1].set(xlabel='Original step distance (confounded by excerpt)',ylabel='Exact probe accuracy',ylim=(-.05,1.05),title='No temporal decay inference')
        for ax in axs:
            handles,_=ax.get_legend_handles_labels()
            if handles:ax.legend(fontsize=7)
        fig.tight_layout();fig.savefig(out/'pilot-curves.png',dpi=180);fig.savefig(out/'pilot-curves.pdf');plt.close(fig)
    print(json.dumps(usage))
if __name__=='__main__':main()
