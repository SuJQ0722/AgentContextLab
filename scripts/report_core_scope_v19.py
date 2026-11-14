"""Exclude controlled/calibration executions from full-benchmark reporting.

The original frozen manifest remains untouched. Three independently audited
replacements supply the latest genuine core result, with SHA-bound evidence.
This module performs no inference, grading, or prediction mutation.
"""
from pathlib import Path
from unittest.mock import patch
import report_once24h_v15 as base

CORRECTION = base.ROOT / 'outputs/controlled-mmbc-vera-nontimeout-v17/source-report-core-corrected.json'


def core_job(job):
    if not job:
        return False
    kind = str(job.get('experiment_kind', '')).lower()
    return not (kind.startswith('controlled') or job.get('benchmark') == 'controlled'
                or job.get('controlled_spec_path') or job.get('controlled_prefix_key')
                or job.get('calibration_not_scored') is True)


def replace_baseline(slot, correction):
    before, after = correction['before'], correction['after']
    if slot['slot_id'] != correction['slot_id'] or slot['selected_completed']['result_sha256'] != before['selected_result_sha256']:
        raise ValueError('Scope correction does not bind the original selected result')
    if after.get('selected_result_path') is not None or after['latest_terminal_status'] not in ('timeout', 'failed'):
        raise ValueError('Expected a documented non-completed core replacement')
    return {**slot, 'selected_completed': None, 'known_score': None,
            'latest_known_result': {'path': after['latest_terminal_result_path'],
                'sha256': after['latest_terminal_result_sha256'], 'status': after['latest_terminal_status']},
            'scope_correction_original_selection': slot['selected_completed']}


class ScopeReporter(base.Reporter):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        correction = self.read(CORRECTION, stable=True)
        if not correction or correction['full_slot_audit_sha256'] != self.bound_sources['baseline_sha256']:
            raise ValueError('Correction requires the exact original manifest')
        rows = correction['corrections']
        if len(rows) != 3 or len({r['slot_id'] for r in rows}) != 3:
            raise ValueError('Expected three separately audited scope corrections')
        for row in rows:
            slot = replace_baseline(self.slots[row['slot_id']], row)
            record = slot['latest_known_result']
            actual = self.result(record['path'], slot, baseline=True, expected_sha=record['sha256'])
            if not actual or not actual['identity_valid'] or not actual['cleanup_confirmed']:
                raise ValueError('Replacement is not a clean genuine core result')
            self.slots[row['slot_id']] = slot
        self.base = {**self.base, 'slots': [self.slots[r['slot_id']] for r in self.base['slots']]}
        self.bound_sources.update(scope_correction_path=str(CORRECTION),
                                  scope_correction_sha256=self.hashes[str(CORRECTION)],
                                  scope_corrected_slots=[r['slot_id'] for r in rows],
                                  scope_filter_source_sha256=base.digest(Path(__file__).read_bytes()))

    def result(self, path, slot, **kwargs):
        value = super().result(path, slot, **kwargs)
        if value and not core_job(self.expected_job(path)):
            value['identity_valid'] = False
            value['source_scope_excluded'] = 'controlled_or_calibration_is_not_full_benchmark'
        return value


if __name__ == '__main__':
    with patch.object(base, 'Reporter', ScopeReporter):
        base.main()
