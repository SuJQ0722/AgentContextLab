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

Each cell has one 8-CPU/32-GiB CCI configured for 16 workers, with no global process cap. Only pending and confirmed failed/timeout tasks are selected. Every completed historical result is retained, including wrong answers. The new recovery queue contains 1,536 attempts.

| Experiment | Attempts | CCI |
|---|---:|---|
| bc_hermes | 80 | acl-vhost-v5-bc-hermes |
| bc_dsh | 107 | acl-vhost-v5-bc-dsh |
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

Deployment status and ETA must be filled from current controller and actual response evidence; CCI creation alone is not proof of model execution.
