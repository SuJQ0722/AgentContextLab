# Rebuttal work and supervision

Updated 2026-11-07. New inference uses the exact configured DeepSeek route;
no new Gemini calls, no fourth repeats, and no pinned-harness changes.

| Work | Scope | Execution and evidence |
|---|---|---|
| Core transfer experiment | BC-100 × 3 × 5 strategies × 2 harnesses = 3,000 | Running, shared 16 workers; highest priority. [Protocol](bc100-campaign.md). |
| Experiment 3 | Summary + native images, window + native images, visual control | Historical-prefix budget calibration finished but failed formal gates. Both fresh native-prefix captures timed out at 1,800 seconds without reaching compression; fresh calibration is blocked and full controlled benchmark results are not available. [Status and blockers](experiment3/README.md). |
| Existing text-table statistics | Reuse historical avg@3 records | Offline reconstruction and paired statistics completed. No extra inference. [Candidate Table 1 audit](paper-table1/audit.md); exact full submitted-table mapping remains unverified. |
| Broad Experiment 4 expansion | Extra repeats across Table 1/2/5 | Skipped at the user's request. Earlier generic statistical drafts remain in `experiment4/` but are not the submitted Table 1. No avg@4 queue exists. |
| Experiment 5 | Failure causes, length buckets, 20 VERA failure cases | Completed from 14,920 historical trajectories, no model calls. [Report](experiment5/experiment5.md). |
| Experiment 6 | Real-trajectory reconstruction and fact probes | Single-trajectory pilot completed. A serial full-canvas study over seven frozen, exactly matched real trajectories is running. [Phase 2](experiment6/phase2.md); [pilot failures and missing observations](experiment6/report.md). |
| New RQ3 experiment | DeepSeek/Hermes BC-100 × 3, seven history scales | Running: 1,800 new trials, 300 reused 1x core observations. New-task concurrency 2, process admission <100. [Protocol](rq3/deepseek-bc100-r3.md). Latest progress is in `outputs/campaigns/rq3-deepseek-bc100-r3/status.json`. |

## Process limits and ownership

The main agent aggregates status. Separate subagents supervise core BC, native
image controls, and information-loss/RQ3 work. Durable local observers continue
when a conversational subagent is idle; this does not promise unsolicited future
chat messages.

The user requires fewer than 128 concurrent visible OS processes. Process counts
are not model-request counts or thread counts. `scripts/monitor_rebuttal.py`
records a 30-second census in `outputs/rebuttal-monitor/status.json` and
`history.jsonl`, with totals for this `/proc` namespace and experiment process
trees. Admission reserves capacity below the ceiling: RQ3 <100 live processes,
native-prefix captures <104, and no more than six supplementary model workers.
The core retains its separate 16-worker pool. Unrelated external processes can
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
