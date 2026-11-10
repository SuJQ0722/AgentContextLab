# Operational handoff v2: do not gate unrelated original groups on global pilot success

The user authorized all original eligible experiments. V1's extra requirement that both pilot groups pass every control gate unnecessarily allowed a network failure in one group to prevent the other 38 original groups from running. V2 removes that **global expansion prerequisite**. It does not relax any scientific control within a group.

```sh
python scripts/watch_controlled_bounded_pilot_v2.py
python -u scripts/watch_controlled_bounded_pilot_v2.py --live --watch
```

The independent watcher waits for all six pilot arms to have known terminal dispositions. Every actual worker must be reaped. Text arms that were never dispatched may be explicitly derived as `not_run_visual_gate_unavailable` from their terminal, reaped visual arm. Pending/active arms cause waiting; orphan dispatches, unknown outcomes, unconfirmed cleanup, or unrecognized terminal states block expansion. The old pilot coordinator must exit and its queue lock must be available.

V2 verifies that V1 has ended blocked without any launch, and holds V1's watcher lock to prevent concurrent handoffs. Once the conditions are met, V2 launches the same frozen full controller once, with its existing one-worker cap and resume behavior. The original 40 eligible groups remain the cohort. No questions are replaced and no prior attempts are replayed. Launch intent is durable; an uncertain launch is never blindly repeated.

Every group's new visual target, actual ±2% text-arm matching, ≤5% realized three-arm spread, identical native evidence, and failure reporting remain unchanged. Failed pilot group gates remain false in the reports; they are not relabeled as passed. Existing offline verification and the observed MMBC calibration support implementation readiness, but do not establish accuracy or cost superiority. Neither correctness nor grade availability selects the resumed cohort.

All changes are confined to the new watcher and `pilot-full-handoff-v2` operational records. The frozen controller, worker, scientific plan, original specs, targets, results, and cost ledgers remain untouched.
