# RQ3: fresh repaired native-vision runs

This campaign is `outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3`: the frozen BC-100 cohort, three paired repeat labels, and seven far-history linear scales (0, 0.125, 0.25, 0.5, 0.7, 0.8, 1). All 2,100 predictions are fresh Hermes runs on `deepseek-v4.1-flash-1017/zijian/sfb`, including the 300 independent 1x controls. They use the repaired v3 native loop, inherited HTTP image/pixel/detail checks, original compression trigger and selection, and the bounded PDF adapter. Gold answers never enter prediction specifications or native workspaces.

Only the far-history `history_scale` setting changes between frozen scale configurations. **0x removes far-history canvases, but retains recent five-round canvases and head/tail native evidence.** It is not a no-image or no-compression baseline. No-compression trajectories have no observed scale intervention and are separately reported. Exposure-conditioned comparisons are descriptive, since compression exposure is itself an outcome.

The old `rq3-deepseek-bc100-r3` queue used the earlier `rq3_hermes_worker.py` / `hermes_bc_worker.py` path and reused an old-core 1x arm. It did not provide the repaired native-vision transport guarantees or a fresh same-route 1x control. Its logs remain historical evidence, but are not pooled into this repaired RQ3 dataset; this does not assert every old call individually failed.

## Launch and recovery

```bash
python scripts/run_rq3_parity_v3.py
python scripts/run_rq3_parity_v3.py --concurrency 16 --resume --live
```

The live entry first performs actual non-model search/fetch readiness checks. It uses one durable controller lock, permanent per-job claims and the original v3 subreaper/deadline supervisor. The local target is 16; shared `experiment_admission_v4.py` admission protects the core's two local workers and keeps visible processes below 128, so actual activity may be lower. No unknown, interrupted or terminal claim is silently retried. SIGTERM stops dispatch and drains active trials. Model retry behavior inside the original Hermes loop remains unchanged.

Configuration, cohort, job list and relevant implementation hashes are frozen in `plan.json`. The former unlaunched dry-run plan is retained as a superseded preparation, with no claims or model calls. The seven intervention configurations and original scientific sources remain unchanged after launch.

## Validation and observed startup

- Localhost real-native-loop fixtures for 0x, 0.125x and 1x passed: `outputs/preflight/rq3-parity-v3-1794200216417828067/result.json`. These exercise native tools, raw usage and canvas-to-wire checks without paid inference.
- Long-history renderer fixture passed all seven scales with distinct image hashes; 0x had no far-history images and retained recent images: `outputs/preflight/rq3-scales-1794200614112549542/result.json`.
- Actual text-mode web readiness passed at 2026-11-09 05:03:54 UTC: `outputs/preflight/bc-v3-web-20261109T050352Z-bf47e12e/result.json`. The controller repeats readiness at startup.
- The live controller started at approximately 05:04 UTC, PID 273504; durable identity and arguments are in `service.json`. By 05:05:48 UTC, 18 returned model calls were recorded. A measured example was 2,908 input tokens, including 768 cached, plus 531 output = 3,439 total. This is startup validation, not an accuracy estimate. `initial-usage-evidence.json` contains no question, answer or credentials.

## Grading and statistical outputs

A separate one-request-concurrency judge watches completed RQ3 trajectories using the same exact SFB model and original Hermes BrowseComp judge prompt/parser. Its private files are under `outputs/grading/rq3-parity-v3-deepseek-sfb-v1`; judge usage is separate from prediction usage. Invalid scores and unknown requests are retained, not silently retried. Gateway pricing is unknown, so dollar cost remains missing.

`report_rq3_parity_v3.py` produces Markdown, CSV and JSON under that grading directory's `analysis/`. It reports each repeat's accuracy, mean and sample standard deviation across three repeats, and a question-cluster bootstrap 95% interval. Each scale is paired with fresh 1x by question/repeat; the two-sided question-level sign-flip test averages repeats within each of 100 clusters. Holm correction covers all six planned comparisons. Full 100×3 coverage at both scales is required before publishing paired inference; missing scores are not converted to incorrect answers. Confirmed terminal failed/timeout attempts count zero operational success, while unknown/not-started/ungraded observations remain missing with accuracy bounds.

Repeat labels are not proof of independent random seeds. A non-significant test does not establish equivalence. These results must be described as this repaired, new SFB experiment, not retroactively substituted into old Gemini or old-renderer tables.
