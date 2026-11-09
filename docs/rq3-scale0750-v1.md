# RQ3 revised seven-scale scope: add 0.75 and exclude 0.125

The requested final scales are **0, 0.25, 0.5, 0.7, 0.75, 0.8, 1**, each with the same 100 questions and three repeat labels. Historical 0.125 results remain archived and are excluded from the revised seven-scale analysis. The original six retained scale cohorts are reused from their original root; they are not rerun in the new root.

The independent root is `outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1`. Its derived plan retains the 2,100-job structural schema required by the frozen validator, but `scale0750-scope.json` authorizes **only the 300 scale_0750 jobs**. The other 1,800 jobs are non-executable placeholders. The manifest binds parent and derived plan hashes, the identical cohort hash, exact authorized job IDs, new source hashes and the explicit scope change. The new trial rejects every placeholder. Final analysis joins only this root's 0.75 observations with the six retained scales from the original root.

The frozen native worker was not directly compatible: `rq3_hermes_parity_worker.py` checks membership in the original `SCALES`, which excludes 0.75. Consequently the new explicit entry points are:

- `prepare_rq3_scale0750_v1.py`: read-only preparation; `validate_scope(root, full=True)` returns `(plan, manifest)` and performs original source/input validation plus new scope checks.
- `run_rq3_scale0750_trial.py`: uses the original supervisor, original metadata/claim/slot ownership checks and timeout handling; validates that the job is authorized, then routes only the native script path to the new worker.
- `rq3_scale0750_worker.py`: accepts only the authorized 0.75 scale and inherits the **same original RQ3VisionRecorder class object**, including repaired final HTTP image/pixel/detail guards and raw usage accounting. Original worker and scale constants are unchanged.

Only far-history canvas linear scale changes for these new observations. Route remains `deepseek-v4.1-flash-1017/zijian/sfb`; recent canvas treatment, retained native evidence, tools, context budget, generation limits and token accounting remain unchanged. The explicit offline-fixture path requires both a fixture marker and a localhost model endpoint, then passes through the native fixture endpoint guard; it cannot authorize a paid production request without a valid scope.

Frozen prepared identifiers:

- Plan SHA256: `992350b26155acbc4350dae606ce09d3015c6545bf16150d2273de50851ec37e`
- Scope manifest SHA256: `5e7f716861141eeef9be11cacd7caff42dc4e114cd57907ed1c4a56b28b6c25e`

Verification was zero paid calls. Four unit tests cover deterministic scope/cohort preservation, original validator and new trial acceptance, placeholder and altered-config rejection, inherited guard identity, and changing only the native command path. A real localhost native loop executes crop/zoom and compression and verifies rendered pixels in final HTTP requests. A separate 14-round PDF fixture compares 0.75 against 1: far-history canvases change, recent-image SHA256 values remain identical, and fallback rendering is prohibited.

Evidence:

- `outputs/preflight/rq3-scale0750-1794208556143638567/result.json`
- `outputs/preflight/rq3-scale0750-render-1794208633686861605/result.json`

These fixtures prove entry/routing/rendering behavior; they are not benchmark accuracy measurements.

The independent private grading namespace is `outputs/grading/rq3-scale0750-v1`. The existing frozen judge protocol has been prepared with zero completed candidates and zero API requests. The exact watcher command and protocol/plan/scope hashes are in the campaign's `grading-watch-prepared.json`. It uses one SFB grading request at a time, preserves unknown/error outcomes without automatic retry, isolates gold from native workers and keeps judge costs separate. Preparation does not create cloud resources or start the live grading watcher; the operational deployment owns those actions.
