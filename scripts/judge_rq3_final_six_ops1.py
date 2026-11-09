#!/usr/bin/env python3
"""Operational scope filter; unchanged grading protocol, ledger and once-only requests."""
import argparse
from pathlib import Path
import sys
import judge_bc_v3_completed as base

VERSION = 'rq3-final-six-judge-ops1'
ROOT = base.ROOT
CAMPAIGN = ROOT/'outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3'
OUTPUT = ROOT/'outputs/grading/rq3-parity-v3-deepseek-sfb-v1'
LABELS = frozenset(('scale_0000','scale_0250','scale_0500','scale_0700','scale_0800','scale_1000'))
FINAL_SCALES = [0., .25, .5, .7, .75, .8, 1.]


def included(job_id):
    parts = Path(job_id).parts
    if len(parts) != 3 or parts[0] != 'hermes' or '..' in parts:
        raise ValueError('Unexpected RQ3 job identity')
    if parts[1] == 'scale_0125': return False
    if parts[1] not in LABELS: raise ValueError('Unexpected RQ3 scale; new .75 has its own grader')
    return True


def scope_record(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if root != CAMPAIGN.resolve() or output != OUTPUT.resolve():
        raise ValueError('This maintenance entry is restricted to original RQ3 grading namespace')
    revision = root/'cloud-scale-ops2/scope-revision-20261109.json'
    data = base.read(revision)
    if data['final_scales'] != FINAL_SCALES or data['excluded_scale'] != .125:
        raise ValueError('User scope revision does not match final seven scales')
    return {'version': VERSION, 'campaign_root':str(root),'grading_root':str(output),
            'included_scale_labels':sorted(LABELS),'excluded_scale':.125,
            'new_scale_grading':'Independent rq3-scale0750-v1 namespace',
            'selection_policy':'Filter before submission; never retry an existing request marker or grade',
            'sources_sha256': {str(path):base.sha(path) for path in
                (Path(__file__).resolve(),Path(base.__file__).resolve(),revision,root/'plan.json')},
            'protocol_policy':'Original protocol.json and per-result provenance remain unchanged',
            'inflight_policy':'Old grader SIGTERM drains already dispatched requests before same lease takeover'}


def install(record):
    original_inventory, original_grade = base.source_inventory, base.grade
    def verify():
        for path, expected in record['sources_sha256'].items():
            if base.sha(path) != expected: raise ValueError('Operational scope source changed')
    def inventory(root, output, cohort):
        verify()
        if str(Path(root).resolve()) != record['campaign_root']:
            raise ValueError('Unexpected campaign root')
        candidates, info = original_inventory(root, output, cohort)
        admitted = [c for c in candidates if included(c['binding']['job_id'])]
        info = dict(info, unfiltered_ready_completed=info.get('ready_completed'),
                    ready_completed=len(admitted), scope_version=VERSION,
                    excluded_ready_completed=len(candidates)-len(admitted),
                    included_scale_labels=sorted(LABELS),
                    inventory_scope_note='prediction_states/existing_grades describe retained historical original plan; ready_completed is filtered')
        info['ready_by_cell'] = {'hermes/visual':len(admitted)} if admitted else {}
        return admitted, info
    def grade(candidate, *args, **kwargs):
        verify()
        if not included(candidate['binding']['job_id']):
            raise ValueError('Excluded scale cannot dispatch a judge request')
        return original_grade(candidate,*args,**kwargs)
    base.source_inventory, base.grade = inventory, grade


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--root',action='append',type=Path)
    parser.add_argument('--output',type=Path,default=OUTPUT)
    args,_=parser.parse_known_args()
    if args.root != [CAMPAIGN] and [p.resolve() for p in (args.root or [])] != [CAMPAIGN.resolve()]:
        raise ValueError('Supply exactly the original RQ3 campaign --root')
    record=scope_record(args.root[0],args.output)
    base.immutable(args.output/'scope-final-six-v1/selection.json',record)
    install(record)
    base.main()

if __name__=='__main__': main()
