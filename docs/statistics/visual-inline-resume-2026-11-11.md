# Direct-image experiment recovery, 2026-11-11 Beijing time

Compression images are sent directly as inline base64. Neither current Hermes nor current DSH compression execution uploads them to ImgBB or another image host. The hosting detour was introduced in orchestration workers, not in the original Hermes compression implementation. Frozen historical files and results remain available for audit.

The outgoing request retains the most recent ten native/canvas image blocks, preserves pixels and configured scales, and never vertically joins pages. A 64 KiB body stream avoids a single large socket write while retaining the original content for request verification. The final inline body admission limit is 32 MiB.

A single measured diagnostic sent the same ten-image, 5,280,272-byte payload that had previously failed its 45-second whole-body write. Chunked transmission succeeded: request-body send 74.213 s, total client wall time 79.515 s, HTTP 200. Observed usage: input 7,213; cached input 7,168; non-cache input 45; output 56; total 7,269. This proves one transmission failure mechanism, not the fraction of all historical timeouts attributable to it, nor representative benchmark latency.

All four authorized routes use the same base model version:

- `deepseek-v4.1-flash-1017/huoshan/huoshan`
- `deepseek-v4.1-flash-1017/zijian/sfb`
- `deepseek-v4.1-flash-1017/huoshan/sfc`
- `deepseek-v4.1-flash-1017/zijian/sfc`

Workers distribute initial routes deterministically and keep a successful route for cache affinity. Eligible refusal, timeout, connection or server errors move to the next route. After all four routes fail, workers back off within the existing task deadline. A global credential failure is terminal. Each HTTP attempt records its actual route, timing and known or unknown usage; failed attempts are retained.

Each cell is configured for 16 workers, with no global process cap. Eleven cells run on separate 8-CPU/32-GiB CCIs. BC Hermes and BC DSH run locally on disjoint eight-CPU affinities because the cloud pool did not have capacity for all thirteen CCIs; the local controllers share the machine's 64-GiB memory. Their original CCIs are suspended to prevent duplicate execution. Only pending and confirmed failed/timeout tasks are selected. Every completed historical result is retained, including wrong answers. The new recovery queue contains 1,536 attempts.

| Experiment | Attempts | Execution location |
|---|---:|---|
| bc_hermes | 80 | Local, CPUs 0–7 |
| bc_dsh | 107 | Local, CPUs 8–15 |
| rq3_scale_0000 | 97 | acl-vhost-v5-rq3-scale-0000 |
| rq3_scale_0250 | 102 | acl-vhost-v5-rq3-scale-0250 |
| rq3_scale_0500 | 120 | acl-vhost-v5-rq3-scale-0500 |
| rq3_scale_0700 | 124 | acl-vhost-v5-rq3-scale-0700 |
| rq3_scale_0750 | 126 | acl-vhost-v5-rq3-scale-0750 |
| rq3_scale_0800 | 125 | acl-vhost-v5-rq3-scale-0800 |
| rq3_scale_1000 | 108 | acl-vhost-v5-rq3-scale-1000 |
| mmbc_vera | 242 | acl-vhost-v5-mmbc-vera |
| mmbc_vanilla | 276 | acl-vhost-v5-mmbc-vanilla |
| controlled_bc | 15 | acl-vhost-v5-controlled-bc |
| controlled_mmbc | 14 | acl-vhost-v5-controlled-mmbc |

Token accounting uses HTTP request/attempt identity to avoid counting both SDK and transport observations of the same successful response. Missing usage remains unknown. Cached/non-cache/output/total tokens and judge costs are reported separately.

Latency is remeasured for this version: end-to-end, rendering, SDK client time, body transmission, response headers/first bytes, stream reception, and actual retry/backoff waits. These timings can overlap and must not be summed indiscriminately. Provider-internal latency is not measured. This is a conditional recovery population, not a representative full 100×3 latency estimate and not directly comparable with historical text-baseline latency.

Controlled cells recover visual branches only. Original native-evidence retention and budget gates are evaluated on actual inline payloads. They do not establish a new matched three-arm comparison against historical text branches.

Artifacts:

- Predictions: `outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v5`
- Grading/resources: `outputs/grading/visual-inline-failure-retry-v5`
- Cloud receipts: `outputs/cloud-runtime/visual-hosted-transport-v5`
- Latency report generator: `scripts/report_visual_transport_latency_v5.py`
- Diagnostic: `outputs/preflight/inline-chunked-transport-v1/result.json`

## Observed execution and forecast

As of 2026-11-10 19:24 UTC (2026-11-11 03:24 Beijing), the two local controllers and eleven cloud cells have started real model requests. Each cell is configured for 16 concurrent trials; the two small controlled queues contain only 15 and 14 trials, so the maximum simultaneous active trials in this recovery wave is 205. Background cloud lifecycle monitoring, local telemetry and grading are running. The grader has completed 24 grading requests without a grading error in the latest audit; this is a moving snapshot, not final experiment accuracy.

DSH BC `q_028_r01` completed a real compressed-context request containing ten inline images (4,415,726 bytes), HTTP 200. Actual undici body-sent elapsed time was 0.397 s, response headers arrived at 190.038 s, and streaming completed at 191.391 s. These are client-observed timings. This successful example shows a remaining wait after body transmission; eliminating image hosting does not remove all provider/network response delay. Its measured usage was cached input 2,304, non-cache input 11,718, output 254, total 14,276.

A separate DSH CLI issue affects the three repetitions of question 043, whose prompt starts with a hyphen. An isolated three-trial supplementary plan uses an explicit CLI argument separator. A persistent waiter starts it after the original DSH queue drains, keeping concurrency at 16. Repetition 1 retains its original failure; repetitions 2 and 3 were atomically deferred before execution and recorded as not_started with zero API calls. The original records and running V5 source remain unchanged. Supplementary plan: `outputs/campaigns/visual-hosted-failure-retry-v1/cells/dsh-cli-separator-v1`; launch receipt: `outputs/cloud-runtime/dsh-cli-separator-v1/launch.json`. No claim of zero failures is made.

Estimated completion of this recovery wave, including grading, is **2026-11-11 12:00–15:00 Beijing time** (04:00–07:00 UTC), conditional on current worker availability and routes continuing to serve requests. This is a planning estimate from queue sizes, 16 workers per cell and existing trial deadlines, not a throughput measurement: the largest queue has 276 attempts, approximately eighteen batches at a 30-minute task deadline, plus startup, cleanup and grading. Most BC/RQ3 queues should finish earlier. Repeated service failures can extend recovery beyond this window, and finishing a retry does not guarantee a successful answer.

See [the latency measurement boundaries](visual-inline-v5-latency.md). Token aliases or missing provider usage remain explicitly unknown; the audit found several conflicting DSH usage aliases, so known token totals must not be presented as complete billed totals.

At 2026-11-11 03:27:42 Beijing, all eleven CCIs were RUNNING/ready1, both local controllers were alive, and 204 trial workers were active. All controllers had stop_dispatch=false. The original two BC CCIs remained suspended. Actual ten-image DSH success evidence is recorded in `outputs/preflight/dsh-inline-ten-image-success-v5.json`.
