"""Reuse the tested asynchronous private scorer for only the transferred never-dispatched grant round."""
from pathlib import Path
from unittest.mock import patch

from lab import ROOT
import judge_once_queue_io_v16 as queue

PREDICTIONS = ROOT / 'outputs/campaigns/mmbc-recent10-pending-v23'
OUTPUT = ROOT / 'outputs/grading/mmbc-recent10-pending-v23'


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    queue.base.immutable(OUTPUT / 'scope-adapter-v23.json', {
        'version': 'mmbc-timeout-private-judge-v23', 'prediction_root': str(PREDICTIONS),
        'grading_root': str(OUTPUT), 'source_sha256': queue.base.sha(__file__),
        'unchanged_queue_sha256': queue.base.sha(queue.__file__),
        'unchanged_scoring_protocol': 'Hermes answer equivalence; model alias validation; first judgments only',
        'concurrency': 4, 'transferred_slots': sum(c['planned_runs'] for c in queue.base.read(PREDICTIONS / 'inventory.json')['cells']), 'prior_grades_not_replayed': True})
    with patch.object(queue.v15, 'PREDICTIONS', PREDICTIONS), \
         patch.object(queue.v15, 'OUTPUT', OUTPUT), \
         patch.object(queue, 'VERSION', 'mmbc-timeout-queued-private-judge-v23'):
        queue.main()


if __name__ == '__main__': main()
