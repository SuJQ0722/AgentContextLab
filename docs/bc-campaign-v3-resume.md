# BC100 v3 scheduler implementation and resume

The plan is always 100 questions × three repeats × two harnesses × five strategies = 3,000 jobs. It is separate from all historical results. `--harness`, `--strategy`, `--concurrency`, and `--limit` select dispatch; they never alter the scientific plan. In particular, `--limit` counts new launches in that controller invocation, not completed jobs or a smaller benchmark.

Initial authorized two-job launch, after commit/review and real web readiness:

```sh
python scripts/run_bc_campaign_v3.py --harness hermes dsh --strategy visual --concurrency 2 --limit 2 --resume --live
```

Each future dedicated harness/strategy instance can use `--harness dsh --strategy visual --concurrency 32 --resume --live`. The 32-slot limit applies to each harness/strategy cell. It is not a global 128-process policy. Instances sharing a cell must mount the **same shared campaign directory**; local copies of the directory cannot coordinate claims. This command is not evidence that a cloud instance exists or was started.

All workers use frozen `experiment.json` and `cohort.jsonl`; DSH receives the explicit cohort file and SHA, rather than rereading a mutable global cohort choice. Source hashes cover the customized Hermes engines/renderer/tools, root native workers and orchestration, shared plugins, compiled DSH modules, and installed pi-ai JavaScript. Monitor/docs are excluded so observation remains maintainable.

Each job has one permanent atomic `claim/` and one `attempts/attempt_001`. A terminal result, interrupted attempt, or claim without a trustworthy result is never retried automatically, even with `--resume`. Cross-host/boot/PID-namespace identities are never treated as local PIDs. Cell slots remain occupied when termination is unknown; manual review is required, not a stale-lock timeout that could duplicate spending.

Controller SIGTERM or campaign `STOP` stops dispatch and drains active trials. A claim caught after stop but before process launch is recorded as `not_started`, with no model call, and keeps its permanent claim. Direct trial interruption is an explicit interrupted outcome. Trial workers enable Linux child-subreaper adoption, track descendants across native process-session boundaries, and release the cell slot only after a durable result and no remaining tracked process. OMP/OpenBLAS/MKL/NumExpr thread limits are one.

Controller status is under `controllers/{hostname-uuid}/status.json`. Trial heartbeats and results are under `jobs/{harness}/{strategy}/{qid}_rNN/attempts/attempt_001/`. Result wrappers retain the native artifact root and native result path; client end-to-end duration is not provider API latency. Native usage/raw-cache/image journals remain intact. Accuracy is `not_judged` until a separately accounted evaluation is performed.

`web-readiness/{hostname}-{boot_id}.json` (with legacy `web-readiness.json` fallback) binds successful real-handler evidence to the frozen configuration, current hostname/boot, and actual check time. It must be at most 15 minutes old when a controller starts because the Reader runs locally on each host. Credentials are not written into this file.

Offline checks: `python -m unittest discover -s tests -p test_bc_campaign_v3.py -v`. Eight tests cover concurrent claims, cell capacity, pending-only resume, foreign-host PID handling, unchanged 3,000-job identity, explicit frozen-cohort commands, native artifact wrapping, and orphan cleanup after a setsid launcher exits. These tests make no model requests.
