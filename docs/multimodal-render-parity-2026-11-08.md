# Multimodal renderer parity audit — 2026-11-08

**The two harness paths do not give native images the same text-wrapped layout.** Sharing the PDF renderer is insufficient to establish parity: DSH removes native image blocks before invoking that renderer. Hermes can embed reachable local image references, but its renderer explicitly skips `data:` image references. The offline paired fixture reproduced both behaviors and the generated images were inspected with `view_image`.

No paid API calls were made, no experiment was resumed, and no frozen implementation was modified. This is a synthetic mechanism audit, not a benchmark accuracy or model-vision result.

## Paired fixture and scope

The common source has identical prose, a deterministic 360 × 220 PNG (red rectangle, blue circle, green triangle), a following caption, a three-row object/count table, and following table commentary. The native PNG SHA256 is `c87b547d28c2a3daa40b9efe00bb724f92e71db1cb4c32a8f28800f3c4bfa8fc` in every condition.

The image is inside a **tool message in the region actually compressed**. Hermes retains three protected prefix messages and one final tool-call round, neither containing images. Thus the observed inline-image omission concerns an image in the selected compression span. It does not imply that images in a protected first user message, or images in an uncompressed tail, disappear.

The fixture uses font 16, scale 1 and the existing highlight layout. Hermes executes actual `VisualEngine.compress`, with its native protected-prefix rule, `keep_rounds=1`, and `recent_rounds=5`. Its accumulated selected source contains six messages. DSH receives equivalent native content blocks for those same six messages, executes the actual exported `separateImages` function, then passes its text result through the unchanged `scripts/render_dsh_history.py` bridge. The bridge's temporary-directory cleanup is disabled only to retain its exact PDF/PNG outputs; its conversion/render arguments are unchanged. The DSH native engine/attachment store/provider loop is not executed by this fixture. The plugin's final separate-native-image assembly is verified from source, while the separator's returned attachment reference and copied source bytes are checked directly.

## Observed result

| Condition | Image inside rendered canvas | Original native image separately retained | Structured table in canvas | Text wrap |
|---|---|---|---|---|
| Hermes local-path reference | Yes, right-side thumbnail | No, for this compressed image | Yes | Around image and table |
| Hermes inline `data:image/png` reference | No | No, for this compressed image | Yes | Around table only |
| DSH native attachment → `separateImages` → renderer | No; `[Native image sha256:…]` text replaces it | Separator retains 1 unchanged reference; plugin appends native image separately | Yes | Around table only, not the native image |

Visual inspection confirms that the Hermes local-path canvas has the three colored shapes at the right with surrounding prose. The inline-data canvas contains the prose and table but none of those shapes. The DSH canvas contains the native-ID placeholder and table but no shapes; its original PNG remains a separate artifact. All three conditions produce one canvas each. These are rendering/input-construction observations, not proofs about final HTTP transmission or provider-side decoding.

The local image is scaled into a thumbnail within the canvas. Therefore even the successful local-path embedding is not preservation of the original native image bytes or resolution. In contrast, DSH's separate attachment can preserve original evidence independently of the canvas, subject to subsequent attachment normalization and final wire checks. Those later stages are outside this fixture.

## Actual code behavior

- `hermes-agent/plugins/context_engine/visual/render.py::_extract_images_from_msg` excludes URLs starting with `data:` and takes at most two image references per message. `_resolve_image_path` accepts existing local files and can download HTTP(S) URLs. The fixture uses local files and performs no downloads.
- `_blocks_to_pdf_bytes` creates `ImageAndFlowables(..., imageSide="right")` for resolved images. This is the actual image/text wrapping observed in the Hermes local-path output.
- `plugins/dsh-context/content.mjs::separateImages` replaces native image blocks with `[Native image <attachmentId>]` and returns the original image blocks separately. `plugins/dsh-context/index.mjs` renders the separated text history, then assembles its visual summary with rendered canvas attachments followed by those original native images. Consequently native images cannot wrap inside this canvas on that path.
- Table extraction is conditional: the tool must be `terminal` or `execute_code`, and its arguments or body must mention a supported data-file extension. The table-source fixture uses `terminal` with `cat evidence.csv`. Both paths then render the table at the right with following commentary wrapping around it.

An earlier control used the same plain pipe table under a generic fixture tool name. Neither path recognized it as structured table data; both flattened it into rendered text. That control is retained separately. It would be inaccurate to claim that every textual table automatically receives table wrapping.

## Reviewable artifacts

Full table-source fixture root: `outputs/preflight/multimodal-render-parity-2026-11-08-table-source-v2/`.

- [Hermes local-path canvas](../outputs/preflight/multimodal-render-parity-2026-11-08-table-source-v2/hermes-local-path/recent_1.png)
- [Hermes inline-data canvas](../outputs/preflight/multimodal-render-parity-2026-11-08-table-source-v2/hermes-inline-data/recent_1.png)
- [DSH separated-native canvas](../outputs/preflight/multimodal-render-parity-2026-11-08-table-source-v2/dsh-separated-native/recent_1.png)
- [Original native evidence](../outputs/preflight/multimodal-render-parity-2026-11-08-table-source-v2/native-evidence.png)
- [Machine-readable report and file hashes](../outputs/preflight/multimodal-render-parity-2026-11-08-table-source-v2/report.json)

Each branch retains `compact_1.pdf`, PNGs, inputs and formatted blocks. The DSH branch additionally retains `separated.json`, `renderer-payload.json`, `normalized-render-input.json` and the separately retained native PNG. `report.json` records all artifact hashes and the implementations' SHA256 values. Common semantic text and native-image identity are recorded in `semantic-source.json`; branch-specific encoded inputs have independent hashes because image representation necessarily differs.

The generic-tool table control is under `outputs/preflight/multimodal-render-parity-2026-11-08/`. The audit script is `scripts/audit_multimodal_render_parity.py`; it refuses an existing output directory and can be run with a fresh `--out` destination. The current script generates the structured CSV-source fixture.

## Implication for experiments

Do not describe Hermes and DSH as identical multimodal layout policies merely because they share the text/PDF renderer. Native-image preservation, canvas composition, image count and provider image-token costs differ. This fixture exposes a concrete loss path for inline-data evidence inside Hermes's compressed region, and a concrete separate-evidence design in DSH. Any repair or layout harmonization requires a separately versioned implementation and final wire/pixel validation; this audit has not enabled such a change or established semantic losslessness.

Renderer token fields in these artifacts are heuristic estimates, including any representation-dependent character counts. They are not measured provider image tokens or API costs; this audit has no provider usage.
