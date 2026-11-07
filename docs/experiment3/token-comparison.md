# Controlled native-image baseline: token comparison protocol

The hypothesis is that visual rendering uses fewer input tokens than text compression plus native images. This is a hypothesis, not a gate for admitting or excluding results. Report VERA, Summarization + Native Images, and Sliding Window + Native Images separately for every benchmark and matched question/repeat.

## Measurements

Record each model call's raw provider usage, including auxiliary summarization calls and any caption calls, then normalize disjoint buckets:

- Cached input: provider-reported cache reads, including an explicit zero when present.
- Non-cache input: prompt tokens minus cache reads, only when both are known and their relationship is valid.
- Output: provider output tokens, including reasoning when included by that provider.
- Total: input plus output; never add cached input twice.
- Image input tokens: only a provider field that actually identifies image tokens. Missing breakdown stays unknown; image dimensions or text-token estimates are not measurements.
- Input-weighted cache hit rate: sum(cached input) / sum(input) over calls where both operands are known. Also report coverage and missing-call count.

Preserve per-call starts, completions, request identifiers, failures and unknown usage. A timeout without returned usage is not zero cost. Show known subtotals and whether the full total is available. Failed runs stay in the fixed cohort; analyses restricted to successful runs must be separately labeled. Rendering time, client API duration, and end-to-end wall time remain separate.

## Comparison and interpretation

Compare both total trajectory cost and the actual first call after each compression. Include auxiliary compression calls in trajectory totals and separately show their contribution. Native image identity, pixel payload and detail settings must match within a paired compression comparison. The text representation is the treatment.

Budget matching controls the maximum post-compression budget and native-image evidence. It does not justify padding one representation to manufacture equal usage. Report realized total input and text/image breakdown where measured, and do not claim budget matching passed when only character estimates were checked.

For each bucket report paired absolute difference (VERA minus baseline) and ratio when the baseline denominator is positive. Neither direction is assumed: lower cached tokens alone is not necessarily desirable, and fewer total input tokens can coexist with more non-cache tokens after canvas updates. Report both buckets, total input, cache-hit rate, accuracy and, only with a verified applicable gateway tariff, dollars. Do not price new DeepSeek calls using Gemini rates.

An isolated prefix replay can measure immediate representation tokens but cannot establish end-to-end cache economics or benchmark accuracy. Provider cache state and request ordering can affect hits; retain timestamps and execution order, label observational hit rates, and do not present repeated identical calibration requests as production cache efficiency.

## Output table

| Benchmark | Method | Fixed cohort / valid scores | Cached input | Non-cache input | Output | Total | Cache hit rate | Missing usage | Image tokens | End-to-end latency | Accuracy |
|---|---|---|---|---|---|---|---|---|---|---|---|

Publish per-question averages only with the denominator and coverage alongside them. Paired differences require the same question content, repeat, model, native evidence and protocol version. Keep calibration, previous failed capture attempts, and new formal evaluation results in distinct rows; report incurred calibration expenditure separately.
