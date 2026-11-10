# BC bounded retry, 2026-11-10

This independent retry applies the same fixed-page visual compression to Hermes and DSH. It preserves all original predictions, failed attempts, grades and accounting. The active queue contains 113 Hermes and 137 DSH observations selected from the original 100 questions × 3 repetitions per harness: 187/163 correct observations are retained; 15/12 completed incorrect observations and 98/125 execution failures receive at most one new attempt.

The retained-correct union is answer-selected, mixes original and new rendering protocols, and is **not an unbiased single-attempt avg@3 result**. Reports must distinguish the original 300 per harness, new conditional retry sample, and operational retained-correct union. Unknown grades remain unknown. All original and new costs remain attributable, including missing provider usage.

Both harnesses use the same renderer: fixed 1024 × 2048 source pages, font16 at72dpi, far pages truly downsampled to .75, recent pages at1.0, separate high-detail images, and pixel-identical lossless WebP transport. Native search/crop/zoom evidence is retained unchanged. The new protocol does not concatenate pages into a long canvas. Exact serialized requests are checked before sending:8MiB maximum,32 images maximum; bounded canvases have side≤2048 and area≤2097152. A limit breach is recorded, not silently repaired by dropping evidence. Existing SDK retry behavior is preserved and raw calls remain separately logged.

Only web_search, web_extract, image_search, image_crop and image_zoom_in are available to the agent. Prediction cohorts include only question IDs and questions. Private reference answers and old correctness reside in the grading namespace; neither file nor shell tools are exposed.

## Execution and capacity

- Plan: `outputs/campaigns/bc-bounded-retry-v1/plan.json`.
- Entrypoints: `prepare_bc_bounded_retry_v1.py`, `run_bc_bounded_retry_v1.py --harness hermes|dsh --concurrency16 --resume --live`.
- Two independent8CPU/32GiB CCI instances, each16 prediction workers, using the approved private image and AFS mount.
- `bc_priority_capacity_ops_v1.py` coordinates all bounded MMBC/RQ3/BC queues, retaining a global inference concurrency upper bound128 and reserving capacity for grading and local diagnostics.
- RQ3 .8 and1.0 stop taking new jobs and naturally drain while the core BC cells have priority. When BC ends, new CCI generations resume the untouched pending RQ3 jobs, after old node termination is confirmed. Already claimed attempts are never automatically replayed.
- Each node must pass actual search/fetch preflight before dispatch. Lifecycle monitors stop only precisely bound, proven-drained instances.

API call durations are measured SDK/HTTP durations, not provider-only processing latency. Cache hit/non-hit/output usage is preserved as returned by the gateway. CLI wall-clock time is reported separately. Full experiment progress remains in the campaign, grading and cloud-runtime namespaces.
