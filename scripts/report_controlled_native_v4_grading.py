#!/usr/bin/env python3
"""Publish answer-free grading coverage with explicit HTTP timing semantics."""
import argparse,copy,fcntl,json,time
from pathlib import Path
from lab import ROOT
from judge_bc_v3_completed import atomic,sha,sha_bytes

def report(source):
    raw=(source/'summary.json').read_bytes();summary=json.loads(raw);usage=copy.deepcopy(summary['judge_usage_separate'])
    usage['client_http_seconds_known']=usage.pop('sdk_client_seconds_known',None)
    usage['client_http_seconds_missing']=usage.pop('sdk_client_seconds_missing',None)
    usage['latency_definition']='Client HTTP request and response-body duration; one HTTP operation, no SDK retry; provider internal time unknown'
    return {'source_summary_sha256':sha_bytes(raw),'source_protocol_sha256':sha(source/'protocol.json'),
        'at':summary['at'],'purpose':'judge','planned':summary['planned'],'selected_terminal':summary['selected_terminal'],
        'matched_prefix_groups':summary['matched_prefix_groups'],'planned_prefix_groups':summary['planned_prefix_groups'],
        'by_cell':summary['by_cell'],'judge_usage_separate':usage,'gold_or_predictions_in_report':False}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,default=ROOT/'outputs/grading/controlled-native-v4-sfb-v1')
    p.add_argument('--output',type=Path,default=ROOT/'outputs/experiment3/controlled-native-v4/grading-status.json');p.add_argument('--watch',action='store_true');a=p.parse_args()
    lease=None
    if a.watch:
        lease=a.output.with_suffix('.watch.lock').open('a');fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    while True:
        atomic(a.output,report(a.source))
        if not a.watch:break
        time.sleep(30)
if __name__=='__main__':main()
