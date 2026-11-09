# Explicit retry selection and private grading

The original BrowseComp-V3 pilot summary failed with `APIConnectionError` during fitting, before a valid first actual continuation. Its original result and raw usage remain unchanged. The user's one-retry authorization is recorded in `outputs/experiment3/controlled-native-v4/attempt-selection-ops2.json`: the new `summary/attempt_002` is selected before its outcome or grade is known. Its spec, prefix, SFB route and frozen v4 worker are identical. Original supervisor and native worker absence were checked before preparing it. A second failure will not create attempt003, nor select the better grade. Costs from both attempts remain included by the existing recursive usage accounting; unknown provider usage is not made zero.

`run_controlled_native_v4_ops2.py` reads this explicit selected-attempt ledger for scheduling, the pilot gate and terminal counts. It preserves pilot4, then requests16 after all six selected pilot results pass the unchanged native/budget gate. It invokes the frozen v4 trial/worker and uses the shared process admission with core2 reservation and visible-process limit below128. The isolated `admission_lock_ops1` maintenance helper only retries EAGAIN while acquiring the shared lock; it never repeats a process spawn or model request. The prior ops1 coordinator had already naturally exited at its failed pilot gate, so this deployment did not terminate any paid child.

Resume the operational coordinator with:

```sh
python scripts/run_controlled_native_v4_ops2.py --live
```

The independent scorer is:

```sh
python scripts/judge_controlled_native_v4.py --live --watch
```

It grades selected completed continuations, including completed results whose comparison group is not yet matched. Scores from unmatched groups are excluded from the matched-comparison statistics. It uses `deepseek-v4.1-flash-1017/zijian/sfb`, concurrency1, output budget8192, one HTTP operation per result and no automatic retry of errors, unknown outcomes or invalid judge responses. Source result, conversation, spec, prefix and control SHA values are checked immediately before grading and bound to the grade. Existing grades with the same binding are reused.

The reused prompt and strict parser are the existing Hermes answer-equivalence implementation used for the local BCV3/MMBC datasets, with the frozen `judge_bc_v3_completed` request/accounting helper. This is not a claim of reproducing an additional official MMBrowseComp checklist score. Gold is read only by the grader and never added to native workspaces. Requests and responses containing gold are written under the mode700 private namespace `outputs/grading/controlled-native-v4-sfb-v1`, with mode600 files. Grading token/cache usage and latency are separate from prediction/fitting costs; absent cache fields, unknown request outcomes and USD remain unknown.

The private `summary.json` reports selected terminal counts, matched valid prefix groups, completed grading coverage and separate grading costs. Accuracy mean/std remain null while a dataset is incomplete or completed matched predictions lack valid grades. When complete, it reports repeat-level accuracy on the explicitly matched subset and its standard deviation, with denominators per repeat; terminal unsuccessful matched trajectories contribute zero to that success-rate statistic without being relabeled factually wrong answers. This subset coverage is never presented as full-benchmark coverage.

Validation: four tests cover preservation of original attempts, fixed outcome-independent selection, refusal while the old worker is alive, and rejection of altered prefixes or unauthorized failures. Three grading tests cover one-request/idempotent behavior, gold isolation, raw cache-zero accounting, SHA mismatch before network, and exclusion of unknown/unmatched budgets. Dry inventory initially found five completed continuations without existing reliable grades.
