# Experiment 6: real-trajectory pilot

This is a single-trajectory pilot, not a completed benchmark evaluation.

| Sample | Method | Step distance | Exact probe QA | Reconstruction answer-substring coverage (not semantic recall) | Status |
|---|---|---:|---:|---:|---|
| s1 | original_text | 14 | 6/6 | 1.0 | completed / stop |
| s1 | render_1.0 | 14 | 6/6 | None | completed / stop |
| s1 | render_0.75 | 14 | 4/6 | 0.6666666666666666 | completed / stop |
| s1 | render_0.5 | 14 | None/6 | 0.8333333333333334 | transport_error / None |
| s1 | summary | 14 | 6/6 | 1.0 | completed / stop |
| s2 | original_text | 9 | 5/6 | 1.0 | completed / stop |
| s2 | render_1.0 | 9 | 5/6 | 0.8333333333333334 | completed / stop |
| s2 | render_0.75 | 9 | 5/6 | 0.6666666666666666 | completed / stop |
| s2 | render_0.5 | 9 | 5/6 | 0.8333333333333334 | completed / stop |
| s2 | summary | 9 | 3/6 | 0.5 | completed / stop |
| s3 | original_text | 4 | 5/6 | 0.16666666666666666 | completed / stop |
| s3 | render_1.0 | 4 | 5/6 | 1.0 | completed / stop |
| s3 | render_0.75 | 4 | 6/6 | 1.0 | completed / stop |
| s3 | render_0.5 | 4 | 6/6 | 1.0 | completed / stop |
| s3 | summary | 4 | 3/6 | 0.6666666666666666 | completed / stop |
| full_canvas | original_full_canvas | None | None/18 | 0.0 | transport_error / None |

## Limitations

- One trajectory, three dependent excerpts; not independent statistical samples.
- Excerpt renders are new representations, not full historical VERA canvases.
- Age is original step distance; no controlled temporal decay claim.
- Original text control is not historical Text-only Rendering ablation.
- Summary is newly generated; post-compression budgets are not matched.
- Same-model fact generation and judging can bias scores; exact-match QA and answer-substring coverage separately reported.
- Original full-canvas reconstruction is output-budget limited.

API records retain raw provider usage, cached prompt details when supplied, client HTTP time, and image dimensions. Image tokens/cost/provider processing time are unknown unless explicitly supplied. Transport errors retain unknown usage and are never silently retried.

Do not interpret correlated snippets as independent samples or claim smooth temporal decay. No confidence intervals are computed for this pilot.

## Provider counters (known subtotal)

```json
{
  "calls_started": 52,
  "calls_returned": 52,
  "missing_usage": 3,
  "input_tokens_known": 35733,
  "cached_input_tokens_known": 0,
  "output_tokens_known": 80121,
  "total_tokens_reported_known": 115854,
  "total_tokens_derived_known": 115854,
  "known_noncache_input_tokens": 35733,
  "client_http_seconds_known": 1245.4438561871648,
  "actual_cost_usd": null,
  "provider_api_seconds": null,
  "image_tokens": null,
  "conservation_checked_calls": 49,
  "conservation_error_calls": 0,
  "cache_conservation_checked_calls": 49,
  "cache_conservation_error_calls": 0,
  "usage_in_flight_unknown": 0,
  "response_count_exceeds_started": false,
  "prompt_observed_calls": 49,
  "prompt_missing_returned_calls": 3,
  "prompt_unknown_calls": 3,
  "output_observed_calls": 49,
  "output_missing_returned_calls": 3,
  "output_unknown_calls": 3,
  "cached_observed_calls": 49,
  "cached_missing_returned_calls": 3,
  "cached_unknown_calls": 3,
  "total_observed_calls": 49,
  "total_missing_returned_calls": 3,
  "total_unknown_calls": 3,
  "derived_total_observed_calls": 49,
  "derived_total_missing_returned_calls": 3,
  "derived_total_unknown_calls": 3,
  "noncache_observed_calls": 49,
  "noncache_missing_returned_calls": 3,
  "noncache_unknown_calls": 3,
  "cached_unknown": 3,
  "full_input_tokens": null,
  "full_output_tokens": null,
  "full_cached_input_tokens": null,
  "full_noncache_input_tokens": null,
  "full_total_tokens": null,
  "usage_complete": false,
  "note": "Known subtotals sum observed fields only; different fields may cover different calls. They are not full campaign totals. Missing/null/invalid fields remain unknown. Non-cache and derived total require both operands from the same response."
}
```

## Metric naming correction

The stored field `reconstruction_exact_fact_recall` is retained for traceability, but its implementation is case-insensitive answer-substring coverage: it checks whether each reference answer string occurs anywhere in reconstructed text. It does not verify the surrounding relation or meaning, lacks token boundaries, may match a short number inside a different number, and misses paraphrases. It is not semantic key-fact recall. Values above retain the original measurements with the corrected label; no frozen live code was changed.
