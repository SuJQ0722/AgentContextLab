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

## Transport-v4 operational recovery

The first launch exposed intermittent hosted-image verification connections, permanent failed-verification markers, an inline-only 8 MiB check before URL substitution, and controlled uploads inheriting inference-only route validation. Dispatch was stopped and every native child drained; 30 newly completed trajectories were retained without consulting answers. All predecessor attempts and costs remain preserved.

The successor has 1,553 attempts, with one independently isolated 16-worker CCI per cell. Core cells were released at 18:13:45 UTC; remaining cells at 18:14:12 UTC (2026-11-11 02:14 Beijing). Actual model activity must be read from current wire/usage records, not inferred from container status.

| Cell | Successor attempts | CCI |
|---|---:|---|
| bc_hermes | 81 | acl-vhost-v4-bc-hermes |
| bc_dsh | 107 | acl-vhost-v4-bc-dsh |
| rq3_scale_0000 | 99 | acl-vhost-v4-rq3-scale-0000 |
| rq3_scale_0250 | 104 | acl-vhost-v4-rq3-scale-0250 |
| rq3_scale_0500 | 122 | acl-vhost-v4-rq3-scale-0500 |
| rq3_scale_0700 | 128 | acl-vhost-v4-rq3-scale-0700 |
| rq3_scale_0750 | 127 | acl-vhost-v4-rq3-scale-0750 |
| rq3_scale_0800 | 129 | acl-vhost-v4-rq3-scale-0800 |
| rq3_scale_1000 | 109 | acl-vhost-v4-rq3-scale-1000 |
| mmbc_vera | 242 | acl-vhost-v4-mmbc-vera |
| mmbc_vanilla | 276 | acl-vhost-v4-mmbc-vanilla |
| controlled_bc | 15 | acl-vhost-v4-controlled-bc |
| controlled_mmbc | 14 | acl-vhost-v4-controlled-mmbc |

New image delivery reuses existing receipts, allows up to two upload attempts per session, retries transient download errors three times through the configured proxy and once directly, and requires identical bytes and pixels. The last ten images are retained. Only the final hosted request has the 8 MiB body limit; canvas dimensions and identity checks remain enforced before hosting. Inference task retries are not hidden in this transport policy.

Every CCI performs actual search/fetch and uncached hosted-image validation before dispatch. DSH additionally validates unauthenticated GET and guarded POST with Unicode content against the gateway. The old DSH TypeError had no cause details and its precise cause remains unproven; v2 adds safe cause codes and has passed actual SDK/local-server integration and gateway preflight. Its first paid responses still need runtime verification.

Validation: 860 root tests passed; all 13 successor native dry-runs passed. Source closure includes local recursive imports. New graded observations live in `outputs/grading/visual-hosted-transport-v4`, prediction plans in `outputs/campaigns/visual-hosted-failure-retry-v1/cells/transport-v4`, and instance receipts in `outputs/cloud-runtime/visual-hosted-transport-v4`.

Initial estimate from configured queue size and task deadlines: about 9–12 hours after release for predictions and grading (roughly 11:15–14:15 Beijing on November 11), subject to actual throughput and successful network/transport validation. This is an estimate, not a measured completion deadline.
