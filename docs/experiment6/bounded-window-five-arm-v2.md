# Grounded fact ordering correction

The v1 release observed valid, exactly grounded fact triples returned in a different order from their source occurrence. Its local source-order guard rejected those sets, so three development windows completed reconstruction but had blocked QA. Those calls, raw usage, results, and classifications remain in the v1 release directory unchanged. The process stopped at a window boundary after 38 completed calls and four windows.

V2 keeps the same six windows, five representations, exact model route, request prompts, 768-token cap, disabled thinking, and single-worker allocation. It validates exact source grounding and answer-free questions, then stable-sorts facts by the first original quote position. This local canonicalization retains all extracted facts and provides the same question order to all five arms.

All 38 completed immutable request/response folders are referenced into the new queue, frozen by hash. Before reusing a result, the runner verifies that the newly constructed request bytes match the original saved request. It makes no repeat paid request. Previously blocked QA and the two untouched windows are the remaining work: at most 64 new calls, within the original 102-unique-call cap. Unknown attempts would prevent preparation; none were present at handoff. Original bad-order classifications remain available for audit, while new results are recomputed under the explicit corrected local rule.

```bash
hermes-agent/.venv/bin/python scripts/run_bounded_window_five_arm_v2.py \
  --reuse-rendered outputs/experiment6/bounded-window-five-arm-v1-release1 \
  --reuse-calls outputs/experiment6/bounded-window-five-arm-v1-release1
hermes-agent/.venv/bin/python -u scripts/run_bounded_window_five_arm_v2.py --live
```

The new root is `outputs/experiment6/bounded-window-five-arm-v2`. All other protocol limits and metric distinctions in `bounded-window-five-arm-v1.md` apply, including the separation between q004 development and q009 holdout and the absence of a population inference claim.
