# Visual memory artifact and delivery audit

Snapshot: 2026-11-07 16:19 UTC. This offline audit makes no model calls, changes no original result, and does not certify semantic losslessness. It separates saved-image integrity from what the main model actually received.

## Observed delivery coverage

The classifier joins archived actual SDK `type=request` messages to agent call IDs/timestamps after the first logged compression event. It inspects message content, not render metadata. These archives are captured SDK request arguments, not an independent network packet capture.

| Campaign | Observed attempts | With compression/render | Confirmed zero images + failed caption replacements | No post-event request observed | No logged compression/render |
|---|---:|---:|---:|---:|---:|
| Core Hermes visual | 35 | 18 | 18 | 0 | 17 |
| New RQ3 Hermes scale attempts | 170 | 84 | 83 | 1 | 86 |

All 226 observed post-compression core requests and all 866 observed post-compression RQ3 requests contain zero image parts and failed image-analysis replacement text. The 18 core and 83 RQ3 affected attempts cannot support successful native-canvas visual-memory claims, even when the original task result says `completed`. The one RQ3 attempt without a subsequent captured request remains unobserved. The 17 core and 86 RQ3 attempts without logged compression are **not invalidated by this finding**. Reused RQ3 1x jobs are covered under core, not counted again as new attempts.

Per-attempt evidence, source archive paths, original statuses and example call IDs are saved in `outputs/visual-integrity-audit/delivery-classification.json`; the reproducible reader is `scripts/audit_visual_delivery.py`. See [the routing audit](vision-routing-audit.md) for concrete request IDs and the DSH evidence boundary.

## Saved-image integrity

| Harness | Jobs with rendered artifacts | Compression events | Image references | Decode failures / uniform images | Page-count mismatches | Expected historical SHA checks | Source-span counter matches |
|---|---:|---:|---:|---:|---:|---:|---:|
| DSH | 9 | 10 | 43 | 0 / 0 | 0 | 43 / 43 | 10 / 10 |
| Hermes | 18 | 33 | 138 | 0 / 0 | 0 | unavailable | unavailable |

There are 180 distinct saved files across 181 image references. All DSH persisted attachment hashes, byte lengths and dimensions match their historical attachment references. Seven DSH attachments explicitly record a resize through `originalDimensions`. The other 36 lack a resize record; this alone cannot exclude same-size re-encoding. Hermes has no expected historical hash/dimension ledger in these records: newly calculated hashes establish the audit snapshot only. Its final `old_*`/`recent_*` canvas count matches each renderer count; intermediate render PNGs are excluded.

For DSH, the recorded `shadowedSeqs` identify the selected source messages. Replaying the plugin's system/checkpoint filtering and cumulative history yields the same message and rendered-text character counts for all ten events. This checks source-span accounting, not semantic equivalence, glyph visibility or absence of clipping inside pages. Hermes did not separately persist the full history accumulator, so its full source-content coverage is not established by this audit.

Machine-readable images, hashes, dimensions, source trace paths and limitations: `outputs/visual-integrity-audit/audit.json`. Reader: `scripts/audit_core_visual_images.py`.

## Actual visual inspection and transformations

The audit opened real image files with `view_image`: DSH `q_001_r01` canvases 1 and 4, and Hermes `q_003_r01` old page 2. They contain text and tool evidence rather than blank canvases. DSH canvas 1 also includes workspace instructions, a system reminder and reasoning; the rendered source is not exclusively tool-result text. Hermes page 2 contains readable Wairarapa passenger numbers, URLs and tool response formatting.

DSH canvas 4 is a particularly dense 693 × 6045 JPEG. Its attachment metadata records an original 1015 × 8854 image, approximately 0.683 of the original linear dimensions. DSH's attachment normalizer can proportionally downscale and re-encode opaque images as JPEG. The default persisted-image limits are 2048² pixels, an 8192-pixel long edge and a 4 MiB encoding target. The archived attachment is therefore not the original renderer PNG, and configured renderer scale 1 does not mean attachment pixels remained unchanged.

The original pre-normalization giant PNG is not present in the q001 attachment store. The renderer uses a temporary directory. Any source-span rerender must be labelled a reconstruction, not a recovered historical file; original unrecorded bytes cannot be certified merely from dimensions.

An offline rerender of q001's exact selected source messages, retaining tool-call structure and using font 16 / scale 1, produced four pages. Pages 1–3 are byte-identical to their historical persisted PNG attachments. Reconstructed page 4 is a 1015 × 8854 PNG of 4,232,666 bytes, matching the historical original-dimension metadata. Its SHA256 is `01b21262f4d283b188c451ac4a0a5a42285d5f5c877fcc50a7b258e94c38b992`. The inputs, selected sequence IDs, output hashes and comparisons are in `outputs/visual-integrity-audit/reconstructed-q001/manifest.json`. This gives the DSH guard a concrete pre-normalization sample for a deterministic conversion check. It is still labelled a reconstruction; at this audit point, the giant PNG-to-historical-JPEG byte comparison has not yet been performed.

The four actual persisted DSH q001 canvases and one Hermes q003 page are listed with image hashes in `outputs/visual-integrity-audit/image-fixtures.json`. Probe questions contain no answers; independently checked answers are stored separately in `probe-reference-answers.json` and must never enter the model request. A probe using these fixtures checks selected readable facts, not exhaustive information preservation.

## Limits for reported results

- Old DSH traces preserve native image references but not serialized outgoing provider HTTP bodies. Their saved images and successful continuation do not independently prove final image delivery. New wire-guard evidence must record actual outgoing image bytes and hashes and be labelled as a new validation, not retroactive proof of old requests.
- BC input is text-only, and all ten audited DSH events have empty `native_image_ids`. These jobs cannot establish preservation of original retrieved images, crops or zooms in a multimodal benchmark.
- Local token estimates are not provider image usage. DSH q001 reports a renderer image-token estimate of 47,171 and a post-compaction meter estimate of 8,389, versus 11,158 measured provider input tokens on the next call. That measured prompt includes all text and images, not image-only tokens. Hermes q003 estimates 18,621 text and 23,554 image tokens and zero token savings; its actual post-compression call has failed caption replacements, so it cannot measure successful visual-compression cost.
- No correctness judging, paid evaluation or changes to frozen experiment implementations were performed for this audit. Existing costs remain recorded even when a visual-memory validity claim is rejected.
