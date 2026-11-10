# Independent bounded-page controlled continuation

`scripts/controlled_native_worker_bounded_v1.py` is an opt-in adapter around the frozen v5 calibration and real Hermes continuation. It does not modify v5 or historical results. **No paid run has been started for this protocol.**

The adapter renders textual prefix history on separate 1024 × 1536 PDF pages, at 16pt/72dpi, scales every page once by .75, and sends high-detail images. It never merges pages into a long strip. Original native evidence is retained separately with identical payload bytes and detail in all three methods. Native tool-image extraction is disabled only during text-page construction to avoid adding those original pictures a second time. Structured tables retain the inherited table layout. This retains the existing Hermes text formatter, including its existing normalization and tool-argument display rules; it is not a claim of byte-for-byte source text rendering.

V5's measured-budget procedure remains unchanged: visual tries fit scales 1, .75, .5, .25; summary/window must each fall within 2% of the new visual provider-measured target, under 16384 prompt tokens. Consequently final canvas linear scale is **.75 × fit scale**, not invariably .75. The adapter records both factors and the product. Independent group validation must still enforce native identity and maximum 5% realized three-arm spread. A ceiling alone is not matched utilization.

The optional explicit spec field `bounded_transport_encoding: bounded-canvas-lossless-webp-v1` encodes only the **post-fit** canvas PNGs as lossless WebP. Each conversion verifies identical decoded RGBA pixels and dimensions, retains source/output byte hashes, and records encoding time. Native originals are never encoded. Without that field, canvases stay PNG. All three methods must use the same declared transport protocol and a new target. This changes transport representation, not the scientific resolution; actual provider token measurements still determine fitting.

The final HTTP guard checks exact serialized bytes: at most 8 MiB, at most 32 images, canvas side at most 2048 and canvas area at most 2,097,152 pixels. A canvas registry is populated from actual final fit/encoding bytes before calibration and continuation calls. Unknown, missing, reordered, or altered canvas pages fail locally. Original native pictures are exempt from canvas geometry limits but remain subject to total request limits. Exceeding a limit causes failure, never silent deletion or additional unreported shrinking.

## Explicit invocation and provenance

The spec must include `bounded_native_protocol` exactly equal to the module's exported `PROTOCOL`, `source_parent_plan_path`, `source_parent_plan_sha256`, and `source_parent_job_id`. The parent job must exist, and question, images, repeat, dataset, threshold, max rounds, and prefix bytes must match. A missing eligible original prefix blocks that job rather than selecting a replacement question. Nonvisual arms require `target_reference_path` within the new namespace, with the same protocol and encoding; the inherited worker additionally checks native identity, prefix hash, route, and valid target usage.

Outputs are restricted to `outputs/experiment3/controlled-native-bounded-v1/<new-attempt>`. Default invocation validates locally and exits without API calls:

```sh
python scripts/controlled_native_worker_bounded_v1.py --spec NEW_SPEC.json --out NEW_OUTPUT
```

`--live` is required for execution. An exclusive worker-started marker and process lock refuse automatic paid attempt replay. Runtime metadata records source/config/spec/prefix hashes. Calibration, summary-generation, and continuation usage remain separately recorded by v5, including unknown usage. Encoding time is reported separately from renderer time and provider/API latency. The adapter adds no model retry loop.

## Validation and interpretation

Offline tests verify actual multi-page PDF rendering and structured table contents, native bytes/detail preservation, final .375 scale reporting for fit .5, post-fit WebP pixel equality and cache reuse, final registry/HTTP guard classification, missing/reordered page rejection, original cohort binding, and rejection of old targets/output namespaces. These tests make no model calls.

The previous fixed 180-arm study cannot become fully paired merely by changing its renderer. Its 60 prefix-unavailable arms include five BC prefixes that never reached the threshold and fifteen MMBC prefixes whose original `image=[]`; those MMBC cases are not damaged inline transfers. The prior selected outcomes include only 20 groups passing budget/native gates and four groups with all three arms completed/scored. New conclusions must state the eligible subset and matched-group denominators; do not substitute questions to fill 180, reuse old visual targets, or hide failed fitting/calibration costs.
