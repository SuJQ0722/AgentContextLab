# Controlled baseline: explicitly authorized third attempt and v5 continuation

The user authorized exactly one additional BCV3 q_001 repeat 1 summary attempt after the two recorded APIConnectionError failures. `controlled_attempts_v5.py` writes an exclusive `attempt-selection-ops3.json` selecting `jobs/browsecomp_v3/q_001_r01/summary/attempt_003` before observing its outcome. The original and attempt_002 results, immutable ops2 selection, raw unknown usage and costs remain. No fourth attempt is authorized or automatically created.

The selected scientific spec is byte-identical to the original (SHA256 `92544c88926cede91bbb88734dba4a10d86ec470b7490faf671f2d6c1bb76452`); question, prefix, native image payload/detail, SFB model, target matching, output limit and wall limit remain unchanged. The runtime spec adds the explicit v5 worker and the same visual reference. The v5 transport changes are described in [controlled-v5-transport-review.md](controlled-v5-transport-review.md). They restore the existing bounded Hermes recovery, retain missing usage, and never relax scientific or image gates.

`run_controlled_native_v5_ops3.py` is an independent persistent coordinator. It validates the original frozen implementation and inputs, uses the existing exclusive queue lease and shared admission ledger, and dispatches `run_controlled_native_v5_trial.py`. The supervisor explicitly invokes the v5 worker with `--live`; future prefix captures also use the v5 diagnostic runtime. All newly dispatched method arms use v5. Existing dispatch/start/result markers prohibit automatic reexecution. Pilot concurrency remains 4; after the two three-arm gates pass, the fixed 180-arm cohort is eligible with target 16, subject to local visible processes below 128 and the shared core-priority reservation. The protocol remains a single-prefix intervention followed by real continuation, not the original repeated-compression benchmark.

The five completed v4 pilot arms were checked before expansion: each has zero provider error rows and zero duplicate archived auxiliary request payloads. The audit is `v5-prior-success-compatibility.json` in the campaign root. These arms used the unchanged successful scientific path; the new recovery code does not retrospectively change them. This does not establish identical cache or latency behavior across runtime versions. Runtime versions and all historical failure costs must remain visible in analysis.

`judge_controlled_native_v5.py` uses the unchanged immutable private judging protocol and original result bindings, while resolving the explicit ops3 selection and naming its grading directory `attempt_003`. The old idle grading coordinator was stopped and its exclusive lease released before the new watcher started. All five existing scores were validated and reused without another judge call. New completed selected results receive at most one SFB judge operation; raw grading costs stay separate. The existing answer-free grading report watcher continues reading the same private summary. Gold is never placed in native workspaces.

Operational entry points (native calls require explicit live mode):

```bash
python scripts/run_controlled_native_v5_ops3.py --root outputs/experiment3/controlled-native-v4 --live
python scripts/judge_controlled_native_v5.py --live --watch
```

Validation: three targeted ops3 tests pass, covering exact attempt_003 selection and attempt_004 rejection, the real supervisor command selecting v5 `--live`, prevention of duplicate execution, and pilot/expanded targets. Frozen input validation and dry run pass. The earlier v5 localhost integration retained zero paid calls and covered transport recovery, native retry exhaustion, and a scientific over-budget stop. Actual third-attempt outcome and gate remain runtime evidence, not asserted by these tests.
