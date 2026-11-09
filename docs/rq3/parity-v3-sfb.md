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

## Operational dispatch handoff

The original controller entered its exception-drain path with `BlockingIOError` after ten launches. It stopped new dispatch and preserved its active native workers. The error type alone does not identify the failing filesystem/lock operation; the original traceback is retained when its drain finishes.

`run_rq3_parity_ops1.py` is a separate operational entry, not a scientific source replacement. It verifies the frozen plan and a fresh, live, exact-identity acknowledgment that the original controller has permanently stopped dispatch in exception drain. Its `cutover-ops1.json` preserves that evidence. A separate exclusive lease prevents two operational dispatchers; original live trials are adopted for capacity accounting, all root slots still share the limit of 16, and all existing claims remain ineligible for launch. The unchanged original supervisors continue owning their native processes.

The only added lock retry is `admission_lock_ops1.py`: bounded retry of explicit `EAGAIN` while acquiring the blocking advisory admission lock, before spawning. It does not retry process creation, ledger I/O or model calls. If process creation succeeds but a later admission write fails, the new controller observes that child and drains it rather than losing track or spawning again. New failures immediately record traceback file/line/function without secret messages or locals. `maintenance-ops1.json` and per-attempt `dispatch-ops1.json` retain operational source hashes; `status-ops1.json` is authoritative for current new dispatch, while the original `status.json` describes only the old draining generation.

The operational entry started as PID 275341 at approximately 05:16 UTC with target 16; actual activity remains resource-limited. Use its saved `service-ops1.json` identity rather than relying on PID alone.

The first compressed 0.5x trajectory subsequently received three successful provider responses and continued tool calls. At 05:15:41 UTC, one response reported prompt 14,882 / cached 12,288 / output 204 / total 15,086, with token conservation. `first-compression-evidence.json` preserves the final HTTP image ledger and raw usage. This proves one real post-compression request/response chain, not universal image readability or final-answer correctness.

## One never-started reservation

The original draining controller held `hermes/scale_0800/q_085_r03` before native launch. Its original attempt directory was empty when audited: no worker-started marker, native directory, tool call or model request. Pending-only dispatch deliberately skips existing claims, so this reservation requires explicit recovery to avoid a permanent missing observation.

`recover_rq3_pre_native_once.py --live --watch` records one fixed authorization under `rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery1`. It waits for the original controller's exact identity to be dead, a matching `drained/stopped` exit record, and the original supervisor's explicit `not_started`, `api_calls=0`, `slot_released=true` result. Any worker/native/unknown file blocks recovery. Original spec and claim hashes must remain unchanged. No model is launched while merely waiting for proof.

Only this one question/scale/repeat is authorized. The overlay retains the full frozen scientific definition for validation, but its other 2,099 entries are unscheduled placeholders, not additional planned work. The safe recovery entry is the script above; do not run the generic whole-campaign scheduler against this overlay. It claims from the **original root's shared 16 slots** and uses the unchanged native trial supervisor, scale, question, route, token/deadline settings and source hashes. The original claim/result are retained. A recovery claim is permanent and never automatically replayed if its outcome becomes uncertain.

After the one prediction terminates, its completed answer is graded once using an isolated output `outputs/grading/rq3-parity-v3-pre-native-recovery1`; judge inference is separately accounted. RQ3 statistics always choose the explicitly authorized overlay observation, irrespective of score, and retain `first-pass-summary.csv`. This fills the same planned repeat rather than adding a fourth seed. Until the proof and result arrive, it remains missing, not incorrect or successful. Unlike a second paid attempt after timeout, this specific recovery requires evidence that the original native attempt made zero calls; reservation wait time is not model API latency.

The durable recovery watcher service is recorded in the overlay root's `watch-service.json`; it began waiting as PID 276494. The statistics watcher was refreshed to apply this fixed selection; its current identity is in the analysis directory's `watch-service.json`.
