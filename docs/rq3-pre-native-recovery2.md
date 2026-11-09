# RQ3 migration reservation: one first native execution

The exact stop acknowledgement for the local RQ3 ops1 controller identifies `hermes/scale_0000/q_043_r01`. Earlier observations of a different reserved job are not authorization for that other job. This is a missing planned observation: the stopped reservation must prove zero native/model calls before any recovery is permitted.

`scripts/recover_rq3_pre_native_ops2.py` uses a separate root `outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3-pre-native-recovery2` and separate grading namespace. It preserves the original plan/spec/claim/attempt, and selects this one new observation independently of outcome or grade. No extra seed or paid prediction retry is created. The prior q085 recovery and its frozen script remain unchanged.

The gate requires all of:

- The exact original host, boot, PID namespace, PID and start identity is demonstrably dead on the same host; an unknown remote identity does not pass.
- `controller-exit-ops1.json` proves the same controller stopped and drained; `status-ops1.json` proves stop-dispatch and zero active children.
- The original attempt contains only `dispatch-ops1.json` and `result.json`. The first is the known maintenance declaration, not a Popen receipt. Any worker-started, command, native, launcher log or unknown file blocks recovery.
- The result is precisely `not_started`, integer `api_calls: 0`, `ops_controller_stopped_before_native_launch`, released slot and no unconfirmed child termination.
- Original plan/spec/claim, exact cutover acknowledgement and maintenance declaration hashes match the authorization. The old slot is no longer owned by that controller.

Only after this proof and a real web preflight may the local single worker claim a slot through `run_rq3_scale_cloud_ops2.acquire_scale_slot`. Its slot is in the same `cloud-scale-ops2/slots/scale_0000` namespace as the cloud worker pool. Thus it consumes one of the shared 16 scale slots; it does not add a seventeenth. The helper also accounts for undrained legacy scale claims. Local process admission remains shared with the core and controlled baseline. Once claimed or spawn becomes ambiguous, this recovery never automatically launches again.

The runtime source and shared slot source hashes are frozen into the authorization. The original native trial, model, tools, rendering and budgets remain unchanged. The reporter accepts exactly this fixed recovery2 job plus the existing q085 recovery1 selection, retaining original first-pass statistics. It does not select a better-scoring result. A private judge runs at most once after the native result is available, with separate billing.

```bash
# Prepare/read-only: no model request.
python scripts/recover_rq3_pre_native_ops2.py
# Authorized one-time watcher; waits for complete never-started proof.
python scripts/recover_rq3_pre_native_ops2.py --live --watch
```

Six new tests cover dead/unknown identity, clean drain, forbidden native evidence, bound cutover hashes, shared-slot/no-double-claim behavior, and fixed result selection. The four original recovery tests and three RQ3 report tests remain passing. A passed test or prepared authorization does not assert the recovery has actually started.
