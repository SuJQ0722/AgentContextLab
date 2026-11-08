# Fixed-route runtime v1

This is an explicit runtime revision, not a rewrite of the frozen scientific plan. The original model route remains the logical model. Analysis must join each attempt's `route-lineage.json` and stratify by `actual_route`; catalog aliases do not prove identical backend weights, prices, caching or independent quotas.

`run_bc_campaign_v3_routes1.py` validates the original sources and uses the existing permanent claims and shared 32-slot cell ceiling. It dispatches `run_bc_trial_v3_routes1.py`, which performs the original trial validation once before creating immutable, fsynced runtime artifacts. The derived config changes only `model`; the derived spec changes only `model` and its config pointer. Original files and previous attempts are untouched. Native entries are `hermes_bc_worker_routes1.py` and `run_dsh_eval_v3_routes1.py`; DSH retains the reviewed capacity1 image transport, complete image guard, and explicit pre-network route guard.

The default assignment file is `outputs/campaigns/bc100-r3-hermes-parity-v3/route-plan-v1.json`, with a companion `route-plan-v1.sha256` containing its SHA256. Explicit `--route-plan` and `--route-plan-sha256` override these paths. Its schema is:

```json
{
  "version": "bc-v3-fixed-routes-v1",
  "parent_plan_sha256": "<original plan SHA256>",
  "logical_model": "deepseek-v4.1-flash-1017/huoshan/huoshan",
  "allowed_routes": ["<approved exact route IDs>"],
  "assignments": [{"question_id": "q_001", "repeat": 1, "actual_route": "<route>"}]
}
```

Every frozen question/repeat pair must appear exactly once. Its ten harness/strategy arms share that route, including auxiliary model calls. Any prior claim lacking route metadata anchors the pair to the original route; incompatible claims fail closed. `runtime/routes1-plan-binding.json` permanently binds the first accepted route plan, so replacing both plan and companion hash cannot silently reassign after restart. No intra-trajectory fallback or retries of old claimed attempts are introduced.

`configs/cloud-dispatch-routes-v1.json` is the independent hot-read operational policy. It has `worker_ceiling_per_instance: 32`, `active_workers_per_cloud_instance`, `local_target_workers`, and explicit exact-route-keyed `per_route_cloud_caps` / `per_route_local_caps` maps. Missing or invalid policy pauses new dispatch. Round-robin selection across assigned routes honors both total and per-route active-trial caps. A route cap of zero leaves its pending jobs unclaimed. Caps are per controller, not provider RPM/TPM guarantees; old pools must fully drain before deployment. A cloud controller selects exactly one harness/strategy cell.

The current intended caps are cloud original=1, zijian/sfb=15, both sfc=0; local original=0, zijian/sfb=2, both sfc=0. Assignment remains fixed while sfc work is held. Concurrency changes affect only future launches and do not signal running trials. Each decision records the operational config hash. If a hot policy changes after a permanent claim but before launch, that reservation is held; it is never silently unclaimed or reassigned.

Every attempt records parent plan/spec/config hashes, runtime spec/config hashes and all new route entry/hook/guard hashes in `route-lineage.json`. Original raw usage remains the accounting authority; returned-model attribution is a separate joined sidecar and must not be summed again. Provider cache unknowns remain unknown. SDK/client elapsed latency is not provider internal latency. Historical costs remain attributable to their original runtime/route.

Offline tests cover original validation failure before any launch, one original validation, immutable source inputs, shared-pair claim anchoring, hash replacement rejection, original shared-slot use, route round robin, and actual scheduler loops producing 1/5/5/5 and 1/15/0/0 launches with zero paid calls. Native route hooks have separate tests for wrong-route/endpoint rejection before network and preservation of the existing image guards. These tests do not establish provider capacity at production concurrency.
