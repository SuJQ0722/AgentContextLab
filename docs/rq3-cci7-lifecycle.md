# RQ3 0.7 CCI completion monitor

`scripts/monitor_rq3_cci7_lifecycle.py` is an operational observer bound to `acl-rq3-s0700-cci7`, UID `292054d96de64ffa8fbee96e4cb94de9`. It makes no model calls and does not change evaluation code, launch markers, other resources, or the separate fifteen local recovery attempts. Default invocation is a single read-only inspection. Only `--watch --live` can submit one official CCI stop.

Before the cloud launch marker exists, the observer only records status. After launch it requires the exact UID-derived node hostname, boot and PID namespace, a current bootstrap exit, the corresponding controller identity (including PID start identity), controller `drained=true`, and terminal results with released slots and no unconfirmed child termination for every claim on that host. A surviving owned slot, missing result, ambiguous controller or mismatched epoch prevents stopping. The controller may finish with an error after a safe drain; this is preserved as failure and still permits releasing the idle cloud resource.

An explicit bootstrap failure before creating a controller can also release the resource, but only with a bound bootstrap exit and no controller or claim evidence. A failure before the bootstrap writes any evidence remains unknown and requires inspection; absence of files alone never authorizes stopping.

The observer publishes an immutable stop request before the official API call. A timeout, rejection or lost response never triggers a second automatic stop request. Subsequent reads record platform state. Exact resource binding, service PID/start identity, status/history, decision evidence and stop receipts live under `outputs/cloud-runtime/rq3-resume-ops5/cci7/lifecycle/`.

Seven zero-model-call tests cover exact identity and drain, missing launch marker, reused PID identity, unconfirmed child termination, pre-controller failure, wrong platform UID, and no repeated stop after an unknown response. The real read-only preflight observed `launch_marker_absent_observe_only`.
