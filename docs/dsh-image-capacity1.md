# DSH image transport capacity1

This is an explicit runtime change relative to the frozen `hermes-parity-v3` plan. Its scientific worker files, experiment configuration, cohort, and historical attempts remain unchanged. New pending attempts may use this runtime; prior failed or claimed attempts are not retried by these entrypoints.

`scripts/run_bc_campaign_v3_capacity1.py` retains the original shared claims, 32 slots per cell, source validation, and pending-only scheduling. It dispatches `scripts/run_bc_trial_v3_capacity1.py`, which retains io2 heartbeat handling and the original one-time frozen validation. Hermes launches the exact original `hermes_bc_worker_v3.py` command. DSH launches `scripts/run_dsh_eval_v3_capacity1.py` with the original arguments.

The new DSH entry has these changes:

- The aggregate inline image ceiling is 64 MiB of base64 image payload, increased from 20 MiB. This is a local ceiling, not a guarantee about TokenHub's accepted payload size.
- The native base bundle instance `image-offload` is disabled. Its package name is `@deepseek-ai/dsh-compaction-image-offload`; using the package name as the patch ID would not disable the actual instance.
- The new guard `dsh_wire_image_guard_capacity1.mjs` inspects actual images before adapting detail. An incomplete request still fails the unchanged count/order/hash/detail checks, while its audit now records the remaining images accurately.
- The per-image pixel, encoded-byte, and dimension limits, model, tools, compression policy, rendering, and output-token budget are unchanged. No image is removed or resized to fit this repair.

Before a new attempt launches, strict atomic writing creates `runtime-lineage.json` with the parent plan SHA, job identity, new code hashes, dependency hashes, transport differences, and compatibility conditions. Existing lineage with different values fails closed. Original already-started/completed attempts are preserved. The controller's maintenance sidecar and native DSH manifest also record the capacity1 runtime. Original scientific source validation still runs; it does not imply this new transport behavior was part of the original plan.

For the same history whose image payload was at most 20 MiB, the successful model-visible request image bytes and detail remain unchanged. This does not promise identical sampled trajectories, costs, or timings. Prior offload failures and their costs, repaired over-limit trajectories, and the operational transition period must remain distinguishable in analysis. Never combine them under an assertion that the whole execution implementation was unchanged.

Validation completed without external HTTP or paid models:

```sh
python -m unittest discover -s tests -p 'test_dsh_capacity1.py' -v
.tools/node-v24.11.0-linux-x64/bin/node --test scripts/test_dsh_capacity1_guard.mjs
python scripts/check_dsh_capacity1_entry.py
```

The six Python tests verify that only the declared adapter configuration changes, the actual instance ID is disabled, the Hermes command is unchanged, validation precedes lineage and launch exactly once, failed validation cannot launch, old attempts are preserved, and the controller loop and guard rejection conditions are unchanged. The Node test verifies that rejecting an incomplete image set logs its actual retained image and does not call transport; a subsequent complete request retains the required detail.

The native CLI replay is recorded at `outputs/preflight/dsh-capacity1-entry-1794129615452124663/result.json`:

| Input | Real retained source | Actual localhost HTTP | Native offload events |
|---|---|---|---:|
| q039 second-compression complete image set | 6 PNGs, 24,203,284 base64 bytes | All original hashes and order received | 0 |
| q048 second-compression complete image set | 4 PNGs, 21,999,488 base64 bytes | All original hashes and order received | 0 |
| q048 set repeated four times | 87,997,952 base64 bytes, above 64 MiB | No HTTP request; one explicit `IMAGE_OFFLOAD_REQUIRED` failure | 0 |

The CLI fixture admits the real retained second-compression canvases as native input images to replay the failing transport condition through the actual new entry. It does not regenerate the original trajectories or compression decisions. Initial image admission uses its normal native detail behavior; the separate original-context replay in `check_dsh_image_offload_failure.mjs` verifies the retained low/high canvas details and all original hashes through the native converter and guard. The existing v3 fixture already exercised real compression routing; the newly measured capacity replay extends transport coverage beyond its previous single small-compression case.

No live campaign was started, stopped, or retried by these offline validation commands.

A separate single paid transport check completed at 2026-11-08 09:22:42 UTC, using the six original q039 canvas hashes/details and the exact configured model route. TokenHub accepted 24,203,284 base64 image bytes (24,204,030-byte HTTP body) with HTTP 200 in 8.7597 seconds of SDK client wall time. Raw usage was 1,890 input, 0 cached input, 1,890 non-cache input, 21 output, and 1,911 total tokens. This engineering check is excluded from benchmark accuracy and benchmark cost; its usage remains recorded separately in `outputs/preflight/dsh-capacity1-live-transport/result.json`. It verifies this observed payload, not universal 64 MiB provider support or semantic reconstruction quality.

The two visual SCO replacement instances were submitted at approximately 09:30 UTC with the capacity1 controller and an operational concurrency of 8 each. The local capacity1 pool started at 09:31:35 UTC with a total target of 8 workers. Text SCO cells retain the io2 controller. All pools share original immutable claims and cell ceilings; no historical attempt was retried.

At 09:45 UTC, the old io2 DSH `none/q_058_r01` also reached the original image ceiling while retaining native images: its last intact request contained 11 PNGs (14,352,307 decoded PNG bytes). The adapter then demanded two oldest images be offloaded; subsequent strict guard failures prevented sending an incomplete set. This proves the repair must cover native-image accumulation in all DSH strategies, not only visual canvases. Before the first DSH ops3 submission, bootstrap routing was extended to use capacity1 for every DSH strategy; Hermes text workers retain io2. Existing old attempts and their errors are preserved. The new runtime still does not change each strategy’s intended history selection.

A real cloud DSH trajectory (`visual/q_062_r01`, capacity1) subsequently completed three compressions and sent eight retained canvases in one successful request at 10:02:06 UTC: 27,965,147 PNG bytes and 37,286,868 base64 bytes, above the former 20,971,520-byte limit. All eight final HTTP image hashes matched retained wire files and traced to the cumulative compression ledger. Raw usage was prompt 8,362 = cached 2,304 + non-cache 6,058; output 189; total 8,551. The model continued tool use. The overall trajectory later reached its original 30-minute deadline; this is proof of successful post-compression transport/inference, not a successful or correct completed answer. Evidence: `outputs/preflight/cloud-ops2-monitor-20261108/dsh-q062-three-compressions-over20mib.json`.
