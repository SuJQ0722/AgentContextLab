# Visual-input repair status — 2026-11-07

**Image-delivery repairs are verified; full-canvas semantic acceptance is not passed. Bulk evaluation remains held.** No frozen campaign or pinned harness implementation was silently changed, and no old affected visual result is relabelled as valid.

| Layer | Hermes corrected wrapper | DSH isolated audit configuration |
|---|---|---|
| Real native compression followed by HTTP image request | Passed localhost fixture, including normal routing | Passed real 32k-trigger compaction fixture |
| Expected image set reaches final HTTP | Pixel/detail/count guard; original full-three-page probes also match payload bytes | Dynamic native-attachment SHA guard; 5/5 images in compaction fixture |
| Raw renderer pixels preserved | Verified for the tested corrected Hermes images | 4/5 raw pages in compaction fixture; oversized fifth page normalized lossily |
| Optional full-pixel tiled layout | Full three-page source reconstructs exactly from 11 tiles; offline candidate | Full reconstructed four-page source reconstructs exactly from 14 tiles; all 14 survive native-to-wire unchanged in zero-API fixture |
| Bounded real-model reading | Explicit-source full-three-page probe at8192 output tokens produced reasoning only, no final answer | Full-four-page probe at8192 requested unavailable tools, no final answer |

The bounded semantic probes deliberately allow one model HTTP request, so these outcomes are not proof that a normal multi-step agent cannot answer, nor proof that DeepSeek lacks vision. They also do not constitute a passing reading test. Original ambiguous passenger/person questions and smaller output budgets are preserved with their limitations instead of being silently regraded.

Hermes has four actual diagnostic requests with known cached384/non-cache11748/output14810/total26942 tokens. DSH's two actual diagnostic requests have known total24538 tokens; the first lacks a cache split. These diagnostics total51480 known provider tokens, without an applicable USD tariff. Local fixtures and image audits make no paid model calls.

## Artifacts

- [Old affected-route evidence](../vision-routing-audit.md)
- [Saved-image and delivery coverage](../visual-integrity-audit.md)
- [Hermes corrected wrapper and probe evidence](hermes-native-v2.md)
- [DSH normalization, wire guard, and probes](dsh-wire-audit.md)
- [Pixel-preserving tiling candidate](../canvas-tiling-candidate.md)
- [Acceptance criteria](../visual-evidence-acceptance.md)

The original core coordinator pause propagated to workers:16 attempts were interrupted and retained. RQ3's coordinator stopped new dispatch and drained its workers. Resume must use an explicitly versioned implementation and retain all earlier costs. The old plans must not be restarted unchanged as if their vision path had been repaired in place. Current web-fetch failures are another independent obstacle to interpreting full benchmark accuracy.
