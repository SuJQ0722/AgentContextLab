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
- Final root checks after the transport repairs: 942 tests passed in 153.764 seconds. All eight actual native worker dry-runs also exited successfully with zero model calls. The transport deadline implementation passed eight focused tests and an independent review.

The next validation population consists of eight prespecified old timeout cases, each in its own versioned cell, with unchanged questions, repeats, compression policy and scientific budgets. These are engineering canaries, not a replacement for complete-cohort results. A whole-wave rerun must not be described as fixed until the new transport and actual trajectories have been checked.

## Same-window transport diagnostic

Two sequential, nonrandomized paid diagnostic requests used the same ten-image payload (5,280,272 bytes), SHA and huoshan/huoshan route, with no automatic retries. Explicit proxy: HTTP 200, client POST body phase 0.00499 s, end-to-end 103.30 s, input 7,213 / cached 0 / output 56. Direct: HTTP 200, body phase 239.74 s, end-to-end 247.93 s, input 7,213 / cached 7,168 / output 56. Both reproduced the same 2/3 reading-check result. The cache conditions differ, so this is not a controlled estimate of population speedup; it supports direct-path transmission delay as a material mechanism. A quick client-to-proxy write is not proof of quick provider ingress. Evidence: `outputs/preflight/python-gateway-proxy-v1/result.json` and `direct-current/result.json`.

After V5 drained and its missing grades were recovered, the idle V5 grader and resource observer received SIGTERM to finish their last snapshots and stop repeatedly scanning static AFS logs. This does not stop prediction workers: all V5 workers were already finished. Audit: `outputs/preflight/visual-inline-v6-canary/old-observers-drain.json`.

## Live canary evidence

The eight selected old timeouts were released locally in independent namespaces after review. Each controller is configured for 16 workers but has only one selected trial. No whole-wave retry or new CCI was launched.

- BC Hermes q004 r01 completed in 110.282 seconds (native runtime 98.062 seconds) and was judged correct. Its predecessor timed out at approximately 1,802 seconds. This one-case comparison also includes initialization and trajectory differences; it is not a population speedup estimate. It did not compress images and is not used as a visual acceptance check.
- RQ3 0.75 has multiple successful requests containing ten independently retained canvases. RQ3 1.0 has successful six-canvas requests. Request identities, original ledgers, exact usage and phase timings are in `outputs/preflight/visual-inline-v6-canary/canvas-success.json`.
- DSH's first eight-canvas request completed with HTTP 200: 4,906,640 bytes, body-sent elapsed 0.397 s, headers 72.038 s, completion 82.441 s; cached input 2,304, non-cache input 9,567, output 1,646, total 13,517. Evidence: `outputs/preflight/visual-inline-v6-canary/dsh-canvas-success.json`.
- Controlled BC completed a request containing five native evidence images plus one canvas. MMBC vanilla recovered after a per-request 300-second deadline by switching route; unreturned usage remains unknown rather than free.

The controlled MMBC canary initially failed before a model call with a transient urllib image-download error. Its original captured images already existed locally. A separate worker and supplemental namespace now validate original URLs/order, ledger hash, actual file hash/size and membership in the frozen prefix before staging identical bytes. Missing or mismatched assets fail closed; no replacement image is fetched. Three focused tests, the actual worker dry-run and exact-byte staging check passed. The supplemental trial has completed its first model request successfully. The original failed trial remains intact. Root: `outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v6-canary/cells/input-reuse-v1`.

These observations verify repaired execution paths, not completion of all eight canaries or elimination of all future timeouts. Native output-budget exhaustion remains a separate limitation. The full recovery wave remains unreleased pending canary review.

The input-reuse controlled MMBC trial subsequently completed a mixed request containing two native images and four canvases after route recovery. Request-level deadlines still occur: some requests had partial response bytes before the 300-second cutoff, while another had no first byte. Existing instrumentation does not record every chunk's timestamp, so these cannot all be labeled continuously generating responses. Neither the repair nor these limited successes establishes elimination of service latency or all future timeouts.

A durable read-only monitor now refreshes every 60 seconds at `outputs/monitoring/visual-inline-canary-v6/monitor.md` and `monitor.json`. It uses the input-reuse supplemental outcome for controlled MMBC while retaining the original failure, keeps prediction and judging usage separate, and does not automatically retry or launch the full wave. It exits after all eight effective observations have terminal outcomes and grading or explicit grading errors.
