"""Read-only usage accounting for controlled continuation and its calibration calls."""
import json
from collections import defaultdict
from datetime import datetime,timezone
from pathlib import Path
from lab import ROOT
from info_loss_report import summarize_usage
from run_bc_trial import atomic
DEFAULT=ROOT/'outputs/experiment3/controlled-native-v2'

def read_lines(path):
    rows=[];bad=0
    if path.exists():
        for line in path.read_text().splitlines():
            try:rows.append(json.loads(line))
            except ValueError:bad+=1
    return rows,bad

def report(root=DEFAULT):
    groups=defaultdict(lambda:{'responses':[],'starts':0,'read_errors':0,'duplicates':0})
    for category in ['jobs','collectors']:
        metric_dirs={p.parent for name in ['calls.jsonl','call-starts.jsonl'] for p in (root/category).glob('**/metrics/'+name)}
        for directory in sorted(metric_dirs):
            path=directory/'calls.jsonl'
            relative=path.relative_to(root/category).parts
            method=relative[-3] if category=='jobs' else 'prefix_collection'
            rows,bad=read_lines(path);starts,bad2=read_lines(path.parent/'call-starts.jsonl')
            unique={r['call_id']:r for r in rows if r.get('call_id')}
            purposes={r.get('purpose','unknown') for r in list(unique.values())+starts}
            for purpose in purposes:
                key=(relative[0],method,purpose);g=groups[key]
                chosen=[r for r in unique.values() if r.get('purpose','unknown')==purpose]
                g['responses'].extend({'usage':r.get('raw_provider_usage')} for r in chosen)
                g['starts']+=len({r['call_id'] for r in starts if r.get('call_id') and r.get('purpose','unknown')==purpose})
                g['read_errors']+=bad+bad2;g['duplicates']+=len(rows)-len(unique)
    result={'as_of':datetime.now(timezone.utc).isoformat(),'rows':[],
      'note':'Known subtotals, not billed dollars. Calibration warms caches; purposes remain separate. Missing image-token breakdown and provider latency are unknown.'}
    for (dataset,method,purpose),g in sorted(groups.items()):
        u=summarize_usage(g['responses'],g['starts']);u['cache_hit_rate_when_complete']=(u['full_cached_input_tokens']/u['full_input_tokens'] if u.get('full_input_tokens') and u.get('full_cached_input_tokens') is not None else None);result['rows'].append({'dataset':dataset,'method':method,'purpose':purpose,
          'usage':u,'read_errors':g['read_errors'],'duplicate_call_ids':g['duplicates']})
    if root.exists():
        atomic(root/'token-accounting.json',result)
        lines=['# Controlled baseline token accounting','',result['as_of'],'',result['note'],'',
          '| Benchmark | Method | Purpose | Cached input known | Non-cache input known | Output known | Total known | Started | Missing usage | In flight |',
          '|---|---|---|---:|---:|---:|---:|---:|---:|---:|']
        for r in result['rows']:
            u=r['usage'];lines.append('| '+' | '.join(str(x) for x in [r['dataset'],r['method'],r['purpose'],u['cached_input_tokens_known'],u['known_noncache_input_tokens'],u['output_tokens_known'],u['total_tokens_reported_known'],u['calls_started'],u['missing_usage'],u['usage_in_flight_unknown']])+' |')
        if not result['rows']:lines+=['','No returned model usage yet.']
        (root/'token-accounting.md').write_text('\n'.join(lines)+'\n')
    return result
if __name__=='__main__':print(json.dumps(report()))
