# Explicit routes2 revision protocol

This implementation adds three separate entries: `bc_route_runtime_v2.py`, `run_bc_trial_v3_routes2.py`, and `run_bc_campaign_v3_routes2.py`. The original routes1 sources, route plan, global binding, claims and incurred results are preserved. Native inference still uses the frozen routes1 Hermes/DSH entries; their lineage-based checks include every original route implementation hash and the new revision sources.

The helper supports only `deepseek-v4.1-flash-1017/{huoshan/sfc,zijian/sfc}` → `deepseek-v4.1-flash-1017/zijian/sfb`. Original-route and existing sfb assignments cannot change. All ten harness/strategy jobs for a question/repeat share one assignment. The code does not generate or publish a real revised plan, create a node, dispatch an evaluation, or retry an old claim.

A revised plan retains the scientific `parent_plan_sha256`, logical model, approved allowlist and full assignment list. It changes `version` to `bc-v3-fixed-routes-v2` and adds:

```json
{
  "parent_route_plan_path": "/absolute/path/route-plan-v1.json",
  "parent_route_plan_sha256": "<original v1 file SHA256>",
  "revision_reason": "<explicit evidence and decision>",
  "cutover_ack_path": "/absolute/path/cutover-ack.json",
  "cutover_ack_sha256": "<immutable acknowledgement SHA256>"
}
```

The v2 file is normally `route-plan-v2.json`, with an explicit `--route-plan`/`--route-plan-sha256` accepted by controller and trial. It binds independently to `runtime/routes2-plan-binding.json`. An existing differing binding fails closed. The v1 binding must already exist and exactly match the original plan; v2 never creates or rewrites it.

At first binding, every changed pair must have no claim directory and no attempt directory, including incomplete or empty directories. Existing unchanged routed claims must carry the exact parent SHA, path, logical model and version and agree with the assignment in both plans. A claim lacking some route metadata is not interpreted as a legacy claim. New claims carry the v2 hash, path and parent lineage.

The immutable cutover acknowledgement uses schema `routes2-dispatch-cutover-v1`, `parent_route_plan_sha256`, `dispatch_config_path` and `dispatch_config_sha256`. `controller_statuses` lists entries with `snapshot_path`, `snapshot_sha256`, and `source_path`; each snapshot must show `stop_dispatch: true`, and the live source must still agree on process identity and stopping status at first binding. Both rejected routes must still have zero local/cloud caps. Every existing controller status must be covered.

For a previously ended local controller whose final status did not set `stop_dispatch`, `inactive_local_controllers` accepts the same snapshot fields. First binding checks exact host/boot/PID namespace identity and the original `owner_alive` function must prove that process identity is gone; an old heartbeat is insufficient. Consequently, first binding with such evidence must occur on that same host. Resume uses the already-established immutable binding and does not require retired hosts to remain available.

The barrier matters because frozen v1 controllers do not acquire a new v2 lock. A v2 lock alone cannot make migration safe while v1 still dispatches. After the barrier, v2 serializes its check-and-claim operations and rechecks sibling claims before native dispatch. Existing native requests can drain normally.

There is a second compatibility gate: v1 preparation rejects a sibling carrying another plan SHA even when its model route is unchanged. Before claiming a v2 sibling, the controller therefore waits until any parent-v1 sibling has either a terminal result or both its matching v1 route lineage and worker-started marker. Waiting leaves the job unclaimed. V2's native entry cannot be used to rerun a parent claim.

Offline tests exercise changed-pair claim/attempt rejection, parent preservation, immutable bindings, wrong SHA/partial metadata, live cutover acknowledgements, the exact-identity local exception, old-preparation deferral, native input derivation and v1-claim refusal. Transport success on a route is not evidence of identical model weights, pricing or semantic performance; analyses must retain actual-route strata and the old costs and failures.
