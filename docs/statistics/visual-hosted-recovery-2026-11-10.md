# Visual failure recovery: 2026-11-10

Released at 17:53:54 UTC (2026-11-11 01:53:54 Beijing time). One CCI per cell, 8 CPU / 32 GiB, 16 configured workers each. No global concurrency cap. Actual activity is recorded separately in each controller status.

Selection is based only on execution status: preserve any historically completed attempt, including wrong or ungraded answers. Retry remaining confirmed failed/timeout observations once in a separate namespace. No old result is deleted.

| Cell | New attempts | Retained completed | CCI | Queue time if every attempt reaches its deadline* |
|---|---:|---:|---|---:|
| bc_hermes | 83 | 217 | acl-vhost-r1-bc-hermes | 3 h |
| bc_dsh | 107 | 193 | acl-vhost-r1-bc-dsh | 3.5 h |
| rq3_scale_0000 | 102 | 198 | acl-vhost-r1-rq3-scale-0000 | 3.5 h |
| rq3_scale_0250 | 105 | 195 | acl-vhost-r1-rq3-scale-0250 | 3.5 h |
| rq3_scale_0500 | 126 | 174 | acl-vhost-r1-rq3-scale-0500 | 4 h |
| rq3_scale_0700 | 132 | 168 | acl-vhost-r1-rq3-scale-0700 | 4.5 h |
| rq3_scale_0750 | 133 | 167 | acl-vhost-r1-rq3-scale-0750 | 4.5 h |
| rq3_scale_0800 | 132 | 168 | acl-vhost-r1-rq3-scale-0800 | 4.5 h |
| rq3_scale_1000 | 112 | 188 | acl-vhost-r1-rq3-scale-1000 | 3.5 h |
| mmbc_vera | 246 | 54 | acl-vhost-r1-mmbc-vera | 8 h |
| mmbc_vanilla | 276 | 24 | acl-vhost-r1-mmbc-vanilla | 9 h |
| controlled_bc | 15 | see selection manifest | acl-vhost-r1-controlled-bc | 1 h |
| controlled_mmbc | 14 | see selection manifest | acl-vhost-r1-controlled-mmbc | 1 h |

*Estimates, not measured throughput or a guaranteed completion deadline. Startup, bookkeeping, process cleanup and grading add time; DSH outer cleanup allowance also adds time. Longest prediction queue is MMBC vanilla, 18 batches at the 30-minute task deadline, about 9 hours before overhead. A first planning range for all predictions and grading is 9–12 hours from release, subject to actual runtime validation.

The transport keeps the last 10 image blocks in message order, counting native images and rendered pages together; canvas files use verified lossless encoding. Uploaded images are downloaded and checked for byte and pixel identity before model submission. Actual hosted-wire ledgers, raw SDK usage, cache tokens and rendering/hosting duration are preserved. SDK wall time must not be described as provider-internal API latency.

BC and MMBC use far-history scale 0.75 and recent-history scale 1.0. RQ3 uses its declared seven scales; 0 omits far history only. MMBC vanilla renders text without embedding visual evidence into its canvases.

Controlled BC/MMBC cells recover only failed visual branches. Their final-wire image retention and budget gates are recorded, and they are explicitly not reported as a valid matched three-arm comparison with previous text branches. Information-loss prediction jobs have no remaining failed visual predictions in the latest completed batch, so no duplicate recovery jobs were submitted for them.

All old and new costs must remain separate and available. Combining old completed results with conditional retries is a recovery view, not a clean single-protocol avg@3.

Validation: 814 root tests passed; 32 focused hosted tests passed; all 13 representative native commands passed dry-run without model calls. The continuous local grader uses four workers and separates judge usage from prediction usage.

Artifacts: `outputs/campaigns/visual-hosted-failure-retry-v1/inventory.json`, per-cell plans and controller statuses, `outputs/cloud-runtime/visual-hosted-failure-retry-v1/release-summary.json`, and `outputs/grading/visual-hosted-failure-retry-v1`.
