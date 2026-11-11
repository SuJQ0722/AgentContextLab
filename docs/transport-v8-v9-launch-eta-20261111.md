# V8/V9 recovery launch and ETA audit

Snapshot: 2026-11-11 18:27 UTC. This is an operational recovery report, not a new scientific score table. No paid calls or launches were made by the auditor.

## Active V8 cells

All 12 controllers have a fresh heartbeat and `stop_dispatch=false`. Eleven have 16 active workers; controlled MMBC has 11 jobs and 11 workers. Total active prediction workers in these cells: 187. Completed durations below are measured end-to-end execution time, not provider API latency.

| Cell | Planned recovery jobs | Completed | Failed/timeout terminal | Active | Completed p50 / p90 (s) | Active-age p50 (min) |
|---|---:|---:|---:|---:|---:|---:|
| bc_hermes | 74 | 1 | 0 | 16 | 202.8 / 202.8 | 21.5 |
| controlled_bc | 16 | 0 | 0 | 16 | No completed sample | 21.1 |
| controlled_mmbc | 11 | 0 | 0 | 11 | No completed sample | 21.3 |
| mmbc_vanilla | 196 | 0 | 0 | 16 | No completed sample | 21.8 |
| mmbc_vera | 218 | 0 | 0 | 16 | No completed sample | 21.3 |
| rq3_scale_0000 | 70 | 13 | 0 | 16 | 159.0 / 409.4 | 19.3 |
| rq3_scale_0250 | 94 | 11 | 0 | 16 | 181.6 / 466.2 | 18.1 |
| rq3_scale_0500 | 107 | 9 | 0 | 16 | 344.6 / 722.5 | 20.8 |
| rq3_scale_0700 | 134 | 7 | 0 | 16 | 152.2 / 257.9 | 20.9 |
| rq3_scale_0750 | 119 | 5 | 0 | 16 | 113.7 / 176.9 | 20.7 |
| rq3_scale_0800 | 122 | 4 | 0 | 16 | 95.5 / 116.3 | 16.4 |
| rq3_scale_1000 | 117 | 7 | 0 | 16 | 189.0 / 385.9 | 16.3 |

This snapshot has 57 completed jobs. Most active jobs already exceed the completed-sample median. The run is only about 17–22 minutes old: long attempts are right-censored and no complete one-hour timeout window has elapsed. Extrapolating only short successful trajectories would materially underestimate completion time.

## V9 replacement cells

| Cell | Frozen jobs | Workers requested | Snapshot state |
|---|---:|---:|---|
| bc_dsh | 102 | 16 | Frozen; new controller heartbeat not yet observed by this audit |
| shared_baselines | 1245 | 16 shared across all nonvisual strategies | Frozen; new controller heartbeat not yet observed by this audit |

V8 bc_dsh/shared_baselines are stopped. Their pre-repair quick failures (17 and 8 terminal results respectively) are engineering failures and do not measure useful new-runtime throughput. V9 supersedes those failed/unstarted executions. Historical successfully completed question-repeat results are retained; retry attempts are not extra seeds. 13 controlled visual calibration jobs are excluded from accuracy and paid judging, while their execution resource cost remains recorded.

## ETA: shared_baselines is the bottleneck

There are 1198 ordinary baseline recoveries plus 47 controlled text arms in one 16-slot container. The 1198 historical recovery candidates include 1080 timeouts (90.2%) and 118 failures. Their previous measured runtime, capped at the new 3600-second single-attempt budget and divided by 16 slots, is 35.51 hours. This is a replay-duration reference, not a forecast: the new runtime, longer per-attempt deadline, repeated timeouts, controlled dependencies and unknown residual timeout rate can change it.

Planning estimate: approximately six days after the V9 workers begin, around **2026-11-17 18:30 UTC** if they start around 2026-11-11 18:30 UTC. Treat this as a provisional capacity budget, not a measured deadline. A one-day completion promise is unsupported.

For an explicit sensitivity model, assume each successful attempt takes 20 minutes, each timeout consumes one hour, a maximum of six attempts, independent per-attempt timeout probability q, full 16-slot utilization, and no further infrastructure outage. Expected wall hours are `(1245/16) × ((1-q)/3+q) × sum(q**k for k in range(6))`. Independence is an estimate; correlated hard cases can be worse.

| Residual timeout probability (assumed) | Estimated shared wall hours | Approximate finish from Nov 11 18:30 UTC |
|---:|---:|---|
| 40% | 77.5 | 2026-11-14 23:59 UTC |
| 50% | 102.1 | 2026-11-16 00:37 UTC |
| 60% | 136.0 | 2026-11-17 10:30 UTC |
| 70% | 183.1 | 2026-11-19 09:35 UTC |
| 90% | 340.3 | 2026-11-25 22:47 UTC |

With every job consuming all six one-hour attempts, the 16-slot packing bound is 468 hours (19.5 days), excluding cleanup, dependency waiting and outages. This is a configuration bound, not the expected duration. The 12 V8 cells run independently; MMBC has at most 84 hours of six-attempt packing for its largest 218-job cell, subject to the same qualifications. Re-estimate after at least one full timeout window and preferably several windows, using all terminal attempts plus active censored time.

## Independent grading watches

Observed processes: V8 PID 1039342; V9 PID 1039441. Both were alive at 18:27 UTC. V9 has a current watcher heartbeat and no eligible completed predictions yet. V8 is still validating/scanning; no HTTP attempt or grade has yet been observed. Do not launch duplicate processes. These are the two production commands for reference:

```bash
cd /mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab
python scripts/judge_inline_model_alias_v9.py \
  --root outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v8-one-hour-retry5 \
  --output outputs/grading/visual-inline-one-hour-retry5-v8 \
  --watch --live --concurrency 4
```

```bash
cd /mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab
python scripts/judge_inline_model_alias_v9.py \
  --root outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v9-runtime-recovery \
  --output outputs/grading/visual-inline-runtime-recovery-v9 \
  --watch --live --concurrency 4
```

Each output directory contains its own `protocol.json`, `summary.json`, `observations.json`, `resources.json`, `status.json`, and per-job bound grades/HTTP usage. The protocol binds the prediction inventory SHA; V9 cannot reuse V8 output. V8 can still grade a completed old DSH/shared prediction, but grades remain separate by result path/SHA. Do not concatenate recovery scores or count both versions as independent seeds: use the frozen scientific question-repeat lineage, preserve already successful executions and replace only eligible failed/timeout executions with their successor.

The V8 watcher does not interpret prediction STOP files as completion. Stopped interrupted/missing DSH/shared rows can keep `all_terminal=false` after the remaining 12 cells finish; terminate that watcher operationally only after active cells finish and eligible grades drain. This is a lifecycle limitation, not score contamination.

## Grading update at 2026-11-11 18:31 UTC

The V8 watcher subsequently produced real successful grades; its initial validation delay was not a crash. Parent requested graceful stop of both old watchers before starting the new alias wrapper. The new wrapper accepts the exact returned name `deepseek-v4.1-flash-1017`, keeps the four request routes unchanged, and preserves original returned-model and token-usage fields. It uses the same output directories and frozen base protocol, with an additional immutable `model-alias-protocol.json`; existing grades are never overwritten or re-requested.

- `visual-inline-one-hour-retry5-v8`: 24 grades; statuses `{'scored': 23, 'judge_error': 1}`; 24 HTTP terminal receipts.
- `visual-inline-runtime-recovery-v9`: 0 grades; statuses `{}`; 0 HTTP terminal receipts.

Validation: four focused offline tests passed, including preservation of the original protocol and immutable alias sidecar; Python compilation and CLI help succeeded. No new judge was launched by this auditor.
