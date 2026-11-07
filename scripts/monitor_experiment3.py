#!/usr/bin/env python3
"""Read-only experiment 3 supervision: native-prefix capture and calibration."""
import argparse,json,time
from datetime import datetime,timezone
from pathlib import Path
from lab import ROOT
from monitor_rebuttal import process_snapshot,read_json
from run_bc_trial import atomic
from info_loss_report import summarize_usage

def lines(path):
    if not path.exists():return [],0
    rows=[];errors=0
    for text in path.read_text().splitlines():
        try:rows.append(json.loads(text))
        except ValueError:errors+=1
    return rows,errors

def snapshot():
    root=ROOT/'outputs/experiment3';cal=root/'native-budget-preflight';capture=root/'prefix-capture'
    responses=[read_json(p) for p in (cal/'calls').glob('*/result.json')]
    calibration={'result':read_json(cal/'results.json'),'usage':summarize_usage([r for r in responses if r],len(list((cal/'calls').glob('*/started.json'))))}
    fresh=root/'native-budget-preflight-fresh'
    fresh_responses=[read_json(p) for p in (fresh/'calls').glob('*/result.json')]
    fresh_calibration={'stage':read_json(capture/'fresh-stage.json'),'result':read_json(fresh/'results.json'),
        'usage':summarize_usage([r for r in fresh_responses if r],len(list((fresh/'calls').glob('*/started.json'))))}
    samples={}
    for ds in ['browsecomp_v3','mmbrowsecomp']:
        folder=capture/ds;rs,errors=lines(folder/'metrics/calls.jsonl');starts,start_errors=lines(folder/'metrics/call-starts.jsonl')
        unique={r['call_id']:r for r in rs if r.get('call_id')};known=[{'usage':r.get('raw_provider_usage')} for r in unique.values()]
        samples[ds]={'result':read_json(folder/'result.json'),'started':read_json(folder/'started.json'),
            'prefix':read_json(folder/'prefix-manifest.json'),'usage':summarize_usage(known,len({r['call_id'] for r in starts if r.get('call_id')})),
            'client_stream_seconds_known':sum(r.get('client_stream_seconds') or 0 for r in unique.values()),
            'stream_timing_observed_calls':sum(r.get('client_stream_seconds') is not None for r in unique.values()),
            'metrics_read_errors':errors+start_errors,'duplicate_completed_call_ids':len(rs)-len(unique),
            'latest_provider_prompt_tokens':next((r['raw_provider_usage'].get('prompt_tokens') for r in reversed(rs) if r.get('raw_provider_usage')),None)}
    ps=process_snapshot();live={p:r for p,r in ps.items() if r['state']!='Z'}
    status={'as_of':datetime.now(timezone.utc).isoformat(),'visible_processes':len(ps),'live_processes':len(live),
        'experiment3_pids':{str(p):r['group'] for p,r in live.items() if (r['group'] or '').startswith('experiment3')},
        'calibration':calibration,'fresh_calibration':fresh_calibration,'captures':samples,'formal_baseline_started':False,'formal_baseline_completed':False,
        'no_new_gemini':True,'capture_threshold':32768,'post_compression_budget':16384,
        'agenticdatabench':'blocked: sandbox unavailable; not launched',
        'note':'Capture is evidence collection, not scored benchmark evaluation. Previous provider prompt controls threshold; the captured next request has not been sent. Client stream/HTTP time is not provider processing time.'}
    atomic(root/'status.json',status)
    with (root/'status-history.jsonl').open('a') as f:f.write(json.dumps({'as_of':status['as_of'],'live_processes':len(live),'capture_states':{d:(r['result'] or {}).get('status','running') for d,r in samples.items()}})+'\n')
    return status

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--watch',action='store_true');args=ap.parse_args()
    while True:
        r=snapshot();print(json.dumps({'as_of':r['as_of'],'live_processes':r['live_processes'],'capture_states':{d:(v['result'] or {}).get('status','running') for d,v in r['captures'].items()}}),flush=True)
        if not args.watch or (all(v['result'] for v in r['captures'].values()) and (r['fresh_calibration']['stage'] or {}).get('state') in ('completed','blocked')):return
        time.sleep(30)
if __name__=='__main__':main()
