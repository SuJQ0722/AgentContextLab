# Inline transport repair, 2026-11-11

The V5 retry wave did not establish reliable execution. Its 1,536 selected prior failures/pending trials contained 299 completed, 1,211 timeout, 24 failed and two CLI-deferred records. Replacing the three q043 DSH records with the separate CLI recovery outcomes gives 300 completed, 1,212 timeout and 24 failed unique observations. These are conditional recovery counts, not a full benchmark accuracy estimate.

## Findings and repairs

1. Hermes forced the model gateway into NO_PROXY, whereas DSH used the configured HTTP proxy. The new Python transport uses an explicit gateway-only proxy independent of environment bypass mutations. Tool traffic retains its existing routing. Client-to-proxy body transmission is not provider receipt or inference time. Same-payload diagnostics are required before drawing end-to-end latency conclusions.
2. DSH's SDK idle watchdog expired after 300 seconds without SDK-visible events even though the transport was buffering a response and rotating routes. The new adapter aligns that watchdog with the existing whole-trial deadline; per-request transport limits and the scientific output budget remain independently enforced. See [the DSH evidence and limitations](../dsh-buffered-watchdog-v1.md).
3. Nine original DSH output-limit failures consumed all 8,192 output tokens as reasoning. Seven occurred on the first model call, before any visual compression. This is not fixed by transport changes. Neither thinking settings nor output budgets were changed to hide these failures. Hermes and DSH retain documented differences in their native truncation handling.
4. Local cold initialization consumed a median 385.5 seconds for the first sixteen Hermes trials and 737.7 seconds for the first sixteen DSH trials. Later initialization was much shorter; cloud initialization was generally around 11–21 seconds. Cold start does not explain the widespread cloud timeouts. New canaries use dependency prewarming without model calls.
5. All 27 missing V5 completed-prediction grades were HTTP 429 errors. The isolated recovery retained the exact answer-equivalence prompt, output budget and scoring parser, rotated the four approved model routes, and recovered all 27 scores. Original requests, failed grades and predictions were preserved. Fifteen responses returned the exact canonical model ID; these were validated from saved responses without another model call.

## Artifacts and verification

- Timeout sample: `outputs/analysis/visual-inline-v5-timeout-sample-20261111/{audit.json,summary.md}`. This is a nonrandom sample of 26 timed-out trajectories, not an estimate of population failure proportions.
- Initialization audit: `outputs/preflight/visual-inline-v5-runtime-diagnosis/initialization.json`.
- Additional judge calls and raw usage: `outputs/grading/visual-inline-judge-recovery-v1`.
- Merged V5 scoring observations: `outputs/grading/visual-inline-judge-recovery-v1/observations-merged.json`. All 299 V5 completed predictions now have a score; the separately graded CLI supplement remains separate.
- Judge recovery: five focused tests pass, including preservation of incorrect scores, no replay of unresolved paid requests, source changes, and offline canonical-model validation.
- Root checks during repair: 932 tests passed in 141.510 seconds. Later transport changes require their own focused verification before release.

The next validation population consists of eight prespecified old timeout cases, each in its own versioned cell, with unchanged questions, repeats, compression policy and scientific budgets. These are engineering canaries, not a replacement for complete-cohort results. A whole-wave rerun must not be described as fixed until the new transport and actual trajectories have been checked.

## Same-window transport diagnostic

Two sequential, nonrandomized paid diagnostic requests used the same ten-image payload (5,280,272 bytes), SHA and huoshan/huoshan route, with no automatic retries. Explicit proxy: HTTP 200, client POST body phase 0.00499 s, end-to-end 103.30 s, input 7,213 / cached 0 / output 56. Direct: HTTP 200, body phase 239.74 s, end-to-end 247.93 s, input 7,213 / cached 7,168 / output 56. Both reproduced the same 2/3 reading-check result. The cache conditions differ, so this is not a controlled estimate of population speedup; it supports direct-path transmission delay as a material mechanism. A quick client-to-proxy write is not proof of quick provider ingress. Evidence: `outputs/preflight/python-gateway-proxy-v1/result.json` and `direct-current/result.json`.

After V5 drained and its missing grades were recovered, the idle V5 grader and resource observer received SIGTERM to finish their last snapshots and stop repeatedly scanning static AFS logs. This does not stop prediction workers: all V5 workers were already finished. Audit: `outputs/preflight/visual-inline-v6-canary/old-observers-drain.json`.
