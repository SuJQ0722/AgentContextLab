"""Read-only selection of annotation-resumed histories before any QA outcomes."""
import argparse,os,time
from pathlib import Path
import probe_qa_v24 as base
from recover_probe_facts_v25 import OUT as REPAIR
from analyze_probe_qa_v24 import analyze
from supplement_recovery_v24 import immutable,read,sha
from lab import ROOT

VIEW=ROOT/'outputs/reports/probe-qa-holdout-v25'
def prepare():
    parent=read(base.OUT/'manifest.json');repair=read(REPAIR/'manifest.json');ids={c['id']for c in repair['cases']}
    value={**parent,'analysis_view':'pre-QA annotation recovery selection; original fixed40 histories',
        'annotation_protocol_variants':['original quote-copy','line-anchored preparation recovery'],
        'parent_manifest_sha256':sha(base.OUT/'manifest.json'),'repair_manifest_sha256':sha(REPAIR/'manifest.json')}
    immutable(VIEW/'manifest.json',value)
    (VIEW/'jobs').mkdir(parents=True,exist_ok=True)
    for case in parent['cases']:
        target=(REPAIR if case['id']in ids else base.OUT)/'jobs'/case['id'];link=VIEW/'jobs'/case['id']
        if link.is_symlink():
            if os.readlink(link)!=str(target):raise ValueError('Frozen analysis selection changed')
        elif link.exists():raise ValueError('Analysis path already occupied')
        else:link.symlink_to(target,target_is_directory=True)

def main():
    p=argparse.ArgumentParser();p.add_argument('--watch',action='store_true');a=p.parse_args();prepare()
    while True:
        done=analyze(VIEW)
        if done:base.report(VIEW)
        if done or not a.watch:break
        time.sleep(60)
if __name__=='__main__':main()
