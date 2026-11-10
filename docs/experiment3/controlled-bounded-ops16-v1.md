# Independent 16-slot controlled-baseline dispatcher

The user explicitly requested 16 concurrent controlled-baseline trials. This operational dispatcher preserves the frozen worker, specs, targets, scientific plan and single-attempt policy. It calls the existing `run_controlled_bounded_v1.py --trial ... --live` supervisor for each new job. Original live native trials count toward the same 16 slots and continue untouched. An unresolved durable dispatch also reserves a slot and is never replayed.

Each group retains visual-first execution, a valid newly measured visual reference before summary/window, identical native image evidence, ±2% individual budget matching, and the independent ≤5% group report. The scope remains all 40 available original prefixes / 120 arms; the other 60 original arms remain unavailable, without replacement questions. Completed/failed/timeout attempts remain intact.

Dry-run, making no API calls or signals:

```sh
python scripts/run_controlled_bounded_ops16_v1.py --capacity-marker outputs/cloud-runtime/bc-controlled-capacity-ops-v3/markers/controlled16.json
```

The main global scheduler must publish an immutable capacity marker before takeover. It contains:

```json
{
  "version": "controlled-bounded-ops16-capacity-v1",
  "ready": true,
  "controlled_native_slots": 16,
  "judge_reserve": 6,
  "global_cap": 128,
  "global_reserved_total": 128,
  "controlled_plan_sha256": "CURRENT_FROZEN_PLAN_SHA",
  "dispatcher_source_sha256": "EXACT_NEW_DISPATCHER_SHA",
  "coordinator_stops": [
    {"pid": 558793, "identity": "897942253"},
    {"pid": 566980, "identity": "898169066"}
  ]
}
```

The reserved total may be below 128 but cannot exceed it. The dispatcher checks the source/plan hashes, exact coordinator identities and command lines. It signals only the old handoff watcher and coordinator using pidfds, waits for them to exit, then obtains the shared queue lock. It never signals a native worker or process group. A PID mismatch, unexpected replacement coordinator, changed marker or occupied queue lock prevents takeover.

```sh
python -u scripts/run_controlled_bounded_ops16_v1.py --capacity-marker outputs/cloud-runtime/bc-controlled-capacity-ops-v3/markers/controlled16.json --takeover --watch-marker --live
```

`--watch-marker` permits waiting without dispatching before the marker exists. Each new supervisor inherits thread limits of one for OMP/OpenBLAS/MKL/NUMEXPR/VECLIB/BLIS. Admission still checks local process and memory capacity under the shared admission lock; the requested cap is 16, not a promise of 16 running under a local resource shortage.

Before spawning, the dispatcher publishes an exclusive durable dispatch record. Exceptions after that point retain an unknown attempt rather than retrying. A known admission denial creates no dispatch or child and can be checked again later. Native retries inside the unchanged frozen worker remain unchanged.

Operational evidence lives under `outputs/experiment3/controlled-native-bounded-v1/ops16-v1/`. Its `status.json` includes `running_native`, `unknown_reserved_slots`, `occupied_slots`, `pending_eligible`, `terminal_eligible`, `all_eligible_resolved`, `no_active_native`, PID/start identity and capacity-marker SHA. The global scheduler must retain the reservation unless all eligible slots are resolved, no native is active, unknown reservations are zero, and the dispatcher has exited. Group gates and raw usage continue in the original report, with the operational cap explicitly annotated as 16. SDK time is not provider latency.

## Local deployment reservation

BC prediction trials run on the two CCI instances. The new dispatcher therefore sets `admission.CORE_WORKERS=0` **only inside its own process**, removing the inherited reservation for two hypothetical future local BC workers. The admission module on disk is unchanged. Actual existing local BC trials still contribute their missing child-process growth through the original `CORE_COST - actual descendants` calculation. The 127-visible-process ceiling and memory-capacity checks remain unchanged.

This deployment choice is recorded in both protocol and status as `local_admission_deployment`. A mock starting with 59 visible processes and no local BC admits all 16 four-process-cost slots at projected 127, and rejects a seventeenth. A separate mock confirms that an existing BC supervisor with one child still reserves three additional processes. These tests verify admission arithmetic, not a promise of 16 active jobs under arbitrary other local workloads.
