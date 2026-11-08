# Rebuttal work and supervision

**2026-11-08: user approved the repaired version and requested resume/start.** Approval is recorded in `outputs/authorization/resume-v3.json`; the previous global pause marker is archived there. Legacy core/RQ3 STOP markers remain, and legacy trajectories/costs are preserved separately. New core execution uses `bc100-r3-hermes-parity-v3`; same-version terminal jobs are reusable, pending jobs can resume, unknown/interrupted requests are not automatically retried. SCO launch is authorized but currently blocked by missing login profile and unresolved cloud resource IDs. See [repair review](repair-review-v3.md) and [SCO plan](sco-review-plan.md).

Updated 2026-11-08 (resume authorized; actual new worker activity is recorded under the new campaign, not inferred from old counts). New inference uses the exact configured DeepSeek route; no new Gemini calls, no fourth repeats, and no pinned-harness changes.

| Work | Scope | Execution and evidence |
|---|---|---|
| Core transfer experiment | BC-100 × 3 × 5 strategies × 2 harnesses = 3,000 | Repaired native-image routing and file-tool isolation passed; approved new-version campaign is being initialized. Two local visual trials (one per harness) are the initial dispatch; 10 cloud cells × 32 workers await SCO credentials. Original 16 interrupted attempts and usage remain separate, without automatic retries. [Protocol](bc100-campaign.md). |
| Experiment 3 | Summary + native images, window + native images, visual control | Historical-prefix budget calibration finished but failed formal gates. The original capture protocol timed out. The versioned fixed-prefix continuation pilot ended with failed readiness gates; no continuation workers are running. A frozen 180-arm small-cohort queue remains gated on six paired pilot outcomes; requested cap 16, shared process admission. [New protocol](experiment3/controlled-v3.md). This is not the original full-trajectory three-benchmark evaluation. [Status and blockers](experiment3/README.md). |
| Existing text-table statistics | Reuse historical avg@3 records | Offline reconstruction and paired statistics completed. No extra inference. [Candidate Table 1 audit](paper-table1/audit.md); exact full submitted-table mapping remains unverified. |
| Broad Experiment 4 expansion | Extra repeats across Table 1/2/5 | Skipped at the user's request. Earlier generic statistical drafts remain in `experiment4/` but are not the submitted Table 1. No avg@4 queue exists. |
| Experiment 5 | Failure causes, length buckets, 20 VERA failure cases | Completed from 14,920 historical trajectories, no model calls. [Report](experiment5/experiment5.md). |
| Experiment 6 | Real-trajectory reconstruction and fact probes | Single-trajectory pilot completed. The serial study over seven frozen, exactly matched real trajectories ended with missing/error observations and no complete cross-scale visual QA cohort; it is not running. [Phase 2](experiment6/phase2.md); [pilot failures and missing observations](experiment6/report.md). |
| New RQ3 experiment | DeepSeek/Hermes BC-100 × 3, seven history scales | New dispatch held after confirmed missing-image evidence. Plan remains 1,800 new trials and 300 reused 1x core observations. Requested new-task concurrency 16; effective runtime concurrency is reported in status.json and remains subject to shared process admission. [Protocol](rq3/deepseek-bc100-r3.md). Latest progress is in `outputs/campaigns/rq3-deepseek-bc100-r3/status.json`. |

## Process limits and ownership

The main agent aggregates status. Separate subagents supervise core BC, native
image controls, and information-loss/RQ3 work. Durable local observers continue
when a conversational subagent is idle; this does not promise unsolicited future
chat messages.

The earlier single-machine allocation required fewer than 128 concurrent visible OS processes. The new requested multi-instance allocation (32 workers per method instance) is prepared separately in [the review plan](sco-review-plan.md); its aggregate exceeds 128 and has user authorization; cloud resource discovery remains blocked on credentials. Process counts
are not model-request counts or thread counts. `scripts/monitor_rebuttal.py`
records a 30-second census in `outputs/rebuttal-monitor/status.json` and
`history.jsonl`, with totals for this `/proc` namespace and experiment process
trees. Admission reserves capacity below the ceiling: RQ3 <100 live processes,
native-prefix captures <104. The later user-requested targets are RQ3 16 and controlled baseline 16; shared admission must account for worker descendants and reserve core capacity. These targets do not authorize exceeding 128 processes.
The old core used a separate 16-worker pool; it is now paused. Unrelated external processes can
change the observed total, so counts are explicitly timestamped measurements.

Observers:

- Core: `scripts/watch_bc_health.py` and `scripts/monitor_bc_campaign.py`.
- Native controls: `scripts/monitor_experiment3.py` if present; canonical status
  is `outputs/experiment3/status.json`.
- Information loss: `scripts/info_loss_report.py` (exits after pilot completion).
- RQ3: `scripts/report_rq3_campaign.py` (does not call models).

The core's standby `scripts/resume_bc_plan.py` uses the same exclusive
coordinator lock. It cannot dispatch alongside the original coordinator. It
preserves every terminal attempt and the 16,384-token DSH post-compression
budget, classifies structurally proven budget-limit failures separately from
unexpected infrastructure failures, and respects STOP/explicit pauses. The
original result files and policy implementations are unchanged.

## Findings that must survive into the rebuttal

1. The archived cohort matching BC-EN 59.8% was selected on the success of four
   compression methods and imputed 41 absent No Compression records as zero.
   The audit reproduces the legacy calculation but does not endorse missing=wrong.
   Overall 69.0% has not been matched to its submitted source.
2. One RQ3 plotting script shifted raw accuracy by +0.9 percentage points and
   relabeled 0.125x as 0.1x. [Unshifted evidence and provenance](rq3/provenance-audit.md)
   preserve the originals and distinguish aggregate points from per-run statistics.
3. Current Text-only Rendering does not automatically caption every image.
   A reproduced table path drops parsed cell values. [Appendix audit](experiment3/text-only-audit.md).
4. Small snippets being readable does not establish full-canvas usability:
   the original four-canvas reconstruction exhausted its output budget without
   final text, and its QA request timed out. These failures remain in the pilot.
5. Three repeats are not three independent question sets. New RQ3 statistics
   will use question-cluster bootstrap and paired differences, not a claim of
   300 independent questions. Non-significance is not proof of equivalence.

All usage totals are known subtotals when any provider counters are missing.
Cached/non-cache/output accounting, client API time, renderer time, and wall time
remain distinct; actual TokenHub USD cost is unknown without an applicable tariff.

The controlled-baseline token hypothesis and accounting rules are specified in [token-comparison.md](experiment3/token-comparison.md). Lower cached and non-cache token counts are to be tested independently; they are not selection criteria.

## Native-image validation hold

The old Hermes visual worker misclassified the configured route and replaced rendered canvases with failed caption text. See [wire-routing audit](vision-routing-audit.md) and [acceptance criteria](visual-evidence-acceptance.md). Rendering success is insufficient. Corrected workers and probes have separate versions; no frozen scientific plan is silently changed. Do not resume old visual queues or count their affected results as native-image evidence.

Current repair/validation outcome: [visual-integrity/status.md](visual-integrity/status.md). Corrected image delivery passed local full-stack tests, but bounded real-model full-canvas reading remains unpassed. No bulk resumption is claimed.
