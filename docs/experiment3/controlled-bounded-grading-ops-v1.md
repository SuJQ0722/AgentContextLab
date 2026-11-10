# Bounded baseline grading and one-shot full handoff

`judge_controlled_bounded_v1.py` retains the approved Hermes answer-equivalence prompt and strict binary parser through `judge_mmbc100.judge_one`, with the exact huoshan route. It grades every new completed trajectory, including those outside the matched comparison subset. Gold and requests stay under `outputs/grading/controlled-native-bounded-v1`; they never enter prediction workspaces.

```sh
python scripts/judge_controlled_bounded_v1.py
python -u scripts/judge_controlled_bounded_v1.py --live --watch --idle-only
```

Only one judge request can run. `--idle-only` checks that no bounded prediction worker is active before starting a request; the predictor may subsequently start, so this is an opportunistic scheduling preference, not a shared mutual-exclusion lock. The main scheduler reserves the judge slot. Started, invalid, failed or unresolved judge requests are never automatically resent.

Confirmed failed/timeout/budget-infeasible executions receive operational score zero. Ungraded completed trajectories and uncertain interruptions stay unknown. Answer score and operational score remain separate if a supervisor timeout coincides with a completed worker artifact. Matched-group reporting requires actual ±2% token matching, ≤5% three-arm spread, and native/prefix/route identity. Every denominator and missing score remains visible; mean/std is withheld while any selected score is unknown or a repeat is absent. All eligible and matched-subset summaries are reported separately. Calibration and failed calls remain in prediction usage; judge usage is separate. Dollar pricing and provider internal latency remain unknown.

`watch_controlled_bounded_pilot_v1.py` is an independent operational watcher; it does not modify the frozen controller or scientific plan:

```sh
python scripts/watch_controlled_bounded_pilot_v1.py
python -u scripts/watch_controlled_bounded_pilot_v1.py --live --watch
```

It requires both original pilot triples to finish with reaped workers and passing actual-budget/native gates. Answer correctness is not an expansion criterion. Once the pilot controller exits, the watcher checks the same controller lock, freezes passing source hashes, and launches the existing controller once without `--pilot-only`, retaining its hard cap of one worker. Failed gates, orphan dispatches, and unknown launch outcomes retain their evidence and stop expansion. The durable launch marker prevents any automatic second launch. Main supervision must explicitly investigate an interrupted handoff.

The scope remains the original 40 available fixed prefixes across BrowseComp-v3 and MMBrowseComp; it is not full three-benchmark coverage.
