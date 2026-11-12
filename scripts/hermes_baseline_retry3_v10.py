"""New retry3 entry; historical worker file and its default contract stay frozen."""
from unittest.mock import patch
import hermes_baseline_inline_worker_v8 as worker
from one_hour_timeout_retry_v10 import validate

def main():
    with patch.object(worker, 'validate', validate):
        worker.main()

if __name__ == '__main__': main()
