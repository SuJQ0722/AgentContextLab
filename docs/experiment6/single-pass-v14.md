# Information loss: one-pass missing-stage recovery V14

This independent protocol retains the fixed ten source trajectories (q004 is
development; nine are holdout), their facts, summaries, complete image pixels,
tile order and high detail. Conditions remain original text, summary, canvas
1.0, 0.75 and 0.5. It is not a new cohort or multimodal benchmark generalization.
Fact age is the observed original `distance_rounds`, not causal time decay.

The frozen plan is `outputs/experiment6/single-pass-v14/plan.json`. Its maximum
new work is **90 HTTP requests: 18 QA, 22 reconstruction and 50 judges**. A
judge dependent on an absent reconstruction may never issue, so this is an
upper bound. Reused generations and all prior failures/unknown acceptances
remain referenced; the new explicit allowance is one request per missing stage,
not a reset of the old retry counter. A new `started.json` permanently consumes
that stage. HTTP errors, timeout and unknown acceptance are never retried.

Successful reconstruction HTTP responses are retained even when truncated by
the output limit. They are not regenerated to improve the outcome. Two old
development QA successes existed only as validated condition records; they are
reused with explicit derived-record bindings, never presented as raw HTTP
responses. All other reuse binds the original response path and SHA.

The new judge identifies supporting **existing span IDs** instead of producing
free-form quotations. Deterministic spans partition every character of the
actual reconstructed output. A supported fact must name valid, nonduplicate
span IDs; unsupported facts must name none. Facts, relation/value/polarity
criteria and the 8192-token, thinking-disabled output ceiling remain fixed.
The judge can still be semantically wrong: valid IDs establish provenance,
not correctness. Same-model judge bias remains a limitation.

Old valid exact-quote judgments are retained under their old judge version.
For a comparable five-arm analysis, all 50 conditions receive the new span-ID
judge when an actual reconstruction output exists. The 17 already valid old
judgments therefore incur one explicitly authorized new-protocol scoring call
each; their successful reconstruction is never regenerated, and old scores are
not overwritten or selected by outcome. New scoring costs are separate.
Cross-method semantic recall uses only the new uniform judge-version subset,
with explicit denominators. QA remains the previous exact
short-answer metric. Missing or invalid judge output is NA, not zero. A length
response may have nonzero recall of its *actual generated output* while its
reconstruction completion flag remains false.

Four condition workers are recommended on one small CCI; up to eight are
supported. Each condition runs its stages sequentially. The controller obtains
a singleton filesystem lock. A durable execution window stops new requests
after at most 23 hours, capped by **2026-11-14 18:20:06 UTC**, and is never
extended on resume. This is a dispatch deadline,
not a guarantee that every dependent request succeeds within 24 hours. No
Reader or web-search process is needed for this experiment.

Launch through the approved private network entry, without placing credentials
in arguments:

```bash
python scripts/network_entry_v13.py --target scripts/info_loss_single_pass_v14.py \
  --root outputs/experiment6/single-pass-v14 --live --concurrency 4
```

`report.json`, `summary.csv` and `facts.csv` refresh after each condition.
They retain per-scale coverage, exact QA, completion, semantic support and
observed distance. New raw usage is aggregated separately from reused costs;
client HTTP duration is not called provider latency. Raw response usage and
missing cache fields remain unmodified. Output artifacts are independent of
all V10/V13 records.

Offline tests cover Unicode-complete spans, rejection of invented evidence IDs,
unknown-start no-retry behavior, and length-output reuse with no completion
credit: `python -m unittest discover -s tests -p test_info_loss_single_pass_v14.py -v`.
