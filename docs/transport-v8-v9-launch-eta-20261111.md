# Inline retry recovery launch and ETA audit

Prediction snapshot: 2026-11-11 18:32 UTC (北京时间 2026-11-12 02:32); information-loss launch verified at 18:37 UTC. Deployment commit on dev: `8e698f02d`. This is an operational recovery report, not a new scientific score table.

## Deployed experiments

Twelve V8 cells and two V9 replacement cells have current controller heartbeats and `stop_dispatch=false`. Thirteen containers have 16 active prediction workers each; controlled MMBC has 11 jobs and 11 active workers. Total: **14 containers, 219 active prediction workers**. No global concurrency cap applies. The V9 cells replace stopped V8 DSH/shared executions; they are not extra independent seeds.

| Runtime | Cell | Frozen recovery jobs | Completed | Failed | Timeout | Active | Heartbeat age (s) |
|---|---|---:|---:|---:|---:|---:|---:|
| V8 | bc_hermes | 74 | 1 | 0 | 0 | 16 | 18.6 |
| V8 | controlled_bc | 16 | 0 | 0 | 0 | 16 | 8.5 |
| V8 | controlled_mmbc | 11 | 0 | 0 | 0 | 11 | 2.5 |
| V8 | mmbc_vanilla | 196 | 0 | 0 | 0 | 16 | 9.0 |
| V8 | mmbc_vera | 218 | 0 | 0 | 0 | 16 | 7.2 |
| V8 | rq3_scale_0000 | 70 | 13 | 0 | 0 | 16 | 8.6 |
| V8 | rq3_scale_0250 | 94 | 11 | 0 | 0 | 16 | 8.1 |
| V8 | rq3_scale_0500 | 107 | 10 | 0 | 0 | 16 | 15.4 |
| V8 | rq3_scale_0700 | 134 | 8 | 0 | 0 | 16 | 14.2 |
| V8 | rq3_scale_0750 | 119 | 5 | 0 | 0 | 16 | 2.6 |
| V8 | rq3_scale_0800 | 122 | 4 | 0 | 0 | 16 | 4.8 |
| V8 | rq3_scale_1000 | 117 | 7 | 0 | 0 | 16 | 17.0 |
| V9 | bc_dsh | 102 | 0 | 2 | 0 | 16 | 29.4 |
| V9 | shared_baselines | 1245 | 0 | 0 | 0 | 16 | 30.8 |

**Observed totals: 59 completed, 2 failed, zero terminal timeouts in these active execution lineages.** The two V9 DSH failures are `output_limit`, not timeout. Main-agent runtime inspection confirms 26 real SSE responses from V9 DSH and complete responses in each of the four DSH and four Hermes baseline strategies in shared_baselines. These are request-level health signals, not 26 completed scientific tasks.

Information-loss V10 is now running in `acl-v10-agentic-info-loss`, UID `634d8ce8d25f4189891c615b684dbdd2`, confirmed RUNNING/ready=1. It has 50 conditions and a 16-worker cap. Seven completed conditions, 25 exact successful requests and one exact canonical-model response were reused without repeat calls. A genuinely new request returned HTTP 200 with complete content: input 28,047 tokens, cached input 28,032, output 582; measured client HTTP time 85.5 seconds. This is client-observed latency, not provider API latency. Proof: `outputs/cloud-runtime/inline-model-alias-v10/actual-native-proof.json`.

The complete deployment is now **15 CCI containers**, each configured for 16 concurrent question/condition workers, total configured ceiling 240. The earlier 219-active snapshot above excludes the subsequently started V10 workers. The two local grading watches have a separate combined ceiling of eight judging requests. Historical Gemini results remain untouched; all new paid evaluation uses DeepSeek. No AgenticDataBench recovery was launched.

All attempts use a one-hour question/condition deadline and at most five additional retries after confirmed timeout (six attempts total). Completed trajectories are retained regardless of correctness. Output-limit and other non-timeout failures are recorded rather than mislabeled as timeouts. Each physical attempt retains raw usage and timing; unavailable usage remains unknown, not zero.

Image transport is inline, with at most the recent ten images; information-loss tiles preserve the source evidence within the ten-image bound. MMBC vanilla and VERA each have a successful canvas-bearing request; VERA evidence includes four canvases plus one native image with matched request hashes. No compression-image hosting call was observed. DSH has live text responses, but its post-compression canvas response was not yet observed in this startup audit.

**Transport remains unstable.** At the first V10 response snapshot, one new response completed and 13 requests had transport errors (ten WriteTimeout, two ConnectError, one ConnectTimeout); route rotation continued. Controlled/MMBC requests also still show read/write failures. Running controllers and some successful image responses do not establish that the timeout problem is solved. Controlled MMBC had no successful canvas response at the last detailed audit.

Historical successfully completed question-repeat results are retained; retries are not additional seeds. Thirteen controlled visual calibration jobs are excluded from accuracy and paid judging, while their native execution cost remains recorded.

## Measured duration evidence and censoring

The following completed-job durations were measured in the preceding 18:25 UTC snapshot. They are end-to-end execution times, not provider API latency. The completed sample is biased toward early finishers; jobs still active at 18:27 UTC already had median ages of about 16–22 minutes. No complete one-hour timeout window had yet elapsed.

| Cell | Completed duration sample | p50 (s) | p90 (s) |
|---|---:|---:|---:|
| bc_hermes | 1 | 202.8 | 202.8 |
| controlled_bc | 0 | Not observed | Not observed |
| controlled_mmbc | 0 | Not observed | Not observed |
| mmbc_vanilla | 0 | Not observed | Not observed |
| mmbc_vera | 0 | Not observed | Not observed |
| rq3_scale_0000 | 13 | 159.0 | 409.4 |
| rq3_scale_0250 | 11 | 181.6 | 466.2 |
| rq3_scale_0500 | 9 | 344.6 | 722.5 |
| rq3_scale_0700 | 7 | 152.2 | 257.9 |
| rq3_scale_0750 | 5 | 113.7 | 176.9 |
| rq3_scale_0800 | 4 | 95.5 | 116.3 |
| rq3_scale_1000 | 7 | 189.0 | 385.9 |

## ETA: shared_baselines is the bottleneck
There are 1198 ordinary baseline recoveries plus 47 controlled text arms in one 16-slot container. The 1198 historical recovery candidates include 1080 timeouts (90.2%) and 118 failures. Their previous measured runtime, capped at the new 3600-second single-attempt budget and divided by 16 slots, is 35.51 hours. This is a replay-duration reference, not a forecast: the new runtime, longer per-attempt deadline, repeated timeouts, controlled dependencies and unknown residual timeout rate can change it.

Planning estimate: approximately six days after the V9 workers begin, around **2026-11-17 18:30 UTC / 北京时间 2026-11-18 02:30** if they start around 2026-11-11 18:30 UTC. Treat this as a provisional capacity budget, not a measured deadline. A one-day completion promise is unsupported.

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

The exact-model-alias wrapper is deployed and both new watcher processes have started: V8 PID **1040924**, V9 PID **1040925**, each with concurrency 4. At the latest process check both were alive; startup validation may precede replacement of the old status-file PID. Both alias protocol sidecars are present. V8 resumed active judging after validating the larger source inventory. Do not start duplicates.

The old watchers drained normally: V8 left 23 successfully scored predictions and one `ConnectError`; V9 had no eligible completed prediction yet. The connection-error receipt records unknown acceptance and unknown token usage, so it remains missing rather than a zero or an automatically overwritten grade. No historical model-alias misclassification was found.

The new wrapper accepts exact returned name `deepseek-v4.1-flash-1017` in addition to existing accepted names, keeps the four request routes unchanged, and preserves raw returned-model and token-usage fields. The frozen base `protocol.json` remains unchanged; `model-alias-protocol.json` binds the wrapper SHA and base-protocol SHA. Existing grades are never overwritten or re-requested.

Production commands, for restart reference only:

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

Each output directory contains its own protocol, summary, observations, resources, status and per-job bound grades/HTTP usage. V8 may finish grading a completed old DSH/shared prediction, but V8/V9 grades remain isolated by result path and SHA. Final scientific aggregation must use each frozen question-repeat lineage and preserve successful historical results; do not concatenate recovery denominators or count execution retries as seeds.

Stopped interrupted/missing DSH/shared rows may keep the V8 watcher from automatically exiting after its remaining 12 cells finish. Stop that watcher operationally after the active cells finish and eligible grades drain. This is a lifecycle limitation, not score contamination.

Validation: four focused offline alias-wrapper tests passed; Python compilation and CLI help passed. Only this documentation was updated during the final audit; frozen execution sources were not edited.
