# DSH image delivery audit — 2026-11-07

This audit distinguishes raw renderer bytes, normalized native attachments, and the final OpenAI-compatible HTTP `image_url` payload. A saved session attachment alone is not proof that an image reached an API request.

## Native compression chain: verified locally

`outputs/preflight/dsh-compaction-wire-1794068929035642722/result.json` records a localhost fixture using the real DSH agent loop, research compaction plugin, renderer, attachment store, and provider adapter. It accumulated actual synthetic tool history through 24 model/tool steps; the configured 32,768-token pressure threshold triggered a valid compression. The unchanged renderer processed 44 messages / 109,275 text characters into five full canvases. The next HTTP request contained five image parts; the localhost server received them and returned a final answer. There were no paid requests.

The versioned observer derived expected hashes dynamically from native `llm/stream` attachment references before the provider adapter. The fetch guard compared the complete ordered image set with those expected identities independently of a question marker. An additional provider config set `requestImageMaxBytes=20 MiB` without changing frozen baseline files.

- Native attachment → final HTTP bytes: **5/5 exact SHA-256 matches**.
- Raw renderer → native attachment → HTTP: **4/5 exact matches**.
- Fifth raw PNG: 1014 × 4845; native attachment and wire: 937 × 4476 JPEG. This is a lossy normalization step and is explicitly recorded, not waived by the guard.
- Post-compression token-meter estimate: 6,326 against the 16,384 budget. This estimate is not a provider-measured image-token count.

The wrapper archived original renderer input and all raw PNGs under that fixture's `raw-canvas/`. The request observer records image geometry, MIME, ordered hashes, and whether `detail` was specified; headers and credentials are excluded. Wire `detail` was omitted. A guard record marked `request_sent` means that fetch was allowed, while the independent localhost receiver establishes actual receipt for these fixture requests.

## Historical complete q001 canvases: additional JPEG loss confirmed

`outputs/preflight/dsh-wire-images-1794068279883863985/audit.json` passed all four real historical q001 native attachments through the real DSH adapter. This is a preload-to-wire fixture, not the native-compaction fixture above.

With the original request-image limit of 1 MiB, all four attachments were JPEG-encoded again. Geometry was unchanged, but neither encoded bytes nor decoded RGB pixels were identical. The request-image encoder uses the JPEG quality ladder 85, 75, 60 and may retain its smallest candidate even when that candidate exceeds the target byte size. Source code evidence: `deepseekHarness/packages/attachment/attachment-local/src/encoding.ts:6`; provider request-image configuration: `deepseekHarness/packages/llm/llm-pi-ai/src/config.ts:378`.

| Page | Native size | RGB MAE (0–255) | Changed pixels |
|---|---:|---:|---:|
| 1 | 1015 × 4070 | 5.63 | 53.94% |
| 2 | 1015 × 4076 | 6.36 | 58.94% |
| 3 | 1014 × 2628 | 5.86 | 55.05% |
| 4 | 693 × 6045 | 7.45 | 79.37% |

These errors measure native attachment → final HTTP re-encoding, not earlier raw-renderer normalization. Machine-readable measurements are in `outputs/visual-integrity-audit/dsh-q001-wire-pixel-error.json`. The fourth historical attachment had already been reduced from 1015 × 8854 to 693 × 6045; its historically saved raw PNG was unavailable. An independent exact-history reconstruction exists, but must be identified as reconstructed source.

## Bounded live reading probes

The unchanged question asks for the birth-year bounds in the USER task at the top and the filename recording the pinned harness version in the workspace instructions. It does not ask for the research task's final person identification. Reference answers are separate and are never included in model requests.

The first complete-four-page probe used a 2,048-output-token limit, below the campaign's 8,192. It returned `max-tokens` with no final text: 10,531 input, 2,048 output, 12,579 total; client stream duration 127.925 s. Cache counts were absent, not zero. Its result is inconclusive within that smaller budget, not a passed reading test. Record: `outputs/preflight/dsh-wire-images-1794068741177702525/{audit,probe-score}.json`.

The separately authorized follow-up used the original 8,192 output budget, the same complete four historical attachments and question, a 360 s hard bound, and 20 MiB request-image configuration with dynamic native-byte guard. All four input attachments reached the HTTP request byte-for-byte. It nevertheless **did not pass the single-call reading check**: the model returned two `bash` tool calls instead of final JSON, although the probe exposed no tools. Those calls returned `unknown tool`; the one-step bound then stopped the run. There was no final answer to grade. This is not evidence that images were omitted or unreadable, and no additional paid retry was made.

Its provider completion was `tool-calls`, not token exhaustion. Measured usage was 6,435 non-cache input + 4,096 cached input + 1,428 output = 11,959 total; client stream duration 168.937 s. Record: `outputs/preflight/dsh-wire-images-1794069029927879547/{audit,probe-score}.json`. The two paid probes consumed 24,538 reported total tokens combined. They differ in both output budget and the explicit request-image byte setting, so they are not an isolated output-budget comparison.

## Scope and limitations

Neither a successful transport fixture nor three readable facts establish task accuracy, whole-history semantic preservation, or raw-canvas losslessness. Increasing only the per-image byte target does not remove the adapter's pixel budget or native normalization. A tiled layout that preserves raw pixels would be a separate experimental variant with a different image count and potentially different token cost. None of these audit patches were applied to the frozen campaign.

Validation: four Node guard unit tests pass, including missing/changed image rejection and ordinary-history title-phrase bypass rejection; the Python entrypoints compile. The real native-compaction localhost fixture additionally verifies the dynamically derived expectation path without a question marker.

## Optional tiled-layout candidate: zero-API wire verification

`outputs/preflight/dsh-wire-images-1794069175906813288/audit.json` sent all 14 tiles of the independently reconstructed four-page q001 source through the real native attachment and HTTP adapter pipeline to localhost, twice. All 14 tile input → native → final wire byte hashes matched; decoded RGB pixels also matched, and both localhost requests received all 14 images. Combined with the tiling manifest’s exact RGBA reconstruction check, this establishes a pixel-preserving delivery candidate for these full pages. This is a separate tiled layout, not a claim about the original four-image campaign, and it made no paid calls or semantic-reading measurements.

The current guard only exempts a title request when its two-message role structure, all five native system-prompt lines, and JSON-array user framing match. A quoted title phrase in ordinary task history cannot disable identity checks.
