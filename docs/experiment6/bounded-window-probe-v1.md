# Bounded local reconstruction diagnostic, 2026-11-10

This is a new, prepared-only protocol. No model calls have been made by its preparer. It does not replace the full-history phase4 measurements or establish full-history information retention.

## Why a new diagnostic is necessary

The previous `paired-repair-phase4-url1` visual inputs already used **7–13 separate tiles, high detail, and tile heights at most 1536 pixels**. Their sources contained 6,247–11,159 whitespace words (52,890–97,686 characters). The aggregate 1x inputs contained 9.64–17.64 million pixels; .75 contained 5.42–9.92 million; .5 contained 2.41–4.41 million. Tiling did not make the reconstruction target shorter.

Across all ten cases, including development case q004:

| Condition | Reconstruction stop | Output length | Provider error | Transport error |
|---|---:|---:|---:|---:|
| Text | 8 | 1 | 0 | 1 |
| Canvas 1x | 1 | 7 | 2 | 0 |
| Canvas .75x | 1 | 5 | 4 | 0 |
| Canvas .5x | 2 | 6 | 2 | 0 |
| Summary | 9 | 0 | 1 | 0 |

All 18 visual `length` responses used 8192 output tokens and reported zero reasoning tokens. Two 1x outputs also exhibited repeated long coded suffixes. Thus thinking exhaustion is not the explanation for these phase4 failures. Long reconstruction targets and some repetitive generation remain problems despite separate tiles and disabled thinking; these observations do not isolate a unique causal mechanism. Readability refusals and infrastructure failures remain failures in the historical report.

For example, q004 has 7,657 source words. Its ten 1x tiles contain 13,301,406 pixels and produced a 2,888-word length-truncated reconstruction. The same ten .75x tiles produced 3,413 words and length truncation; .5x stopped at 412 words. A short stopped answer is not evidence of complete reconstruction.

The per-condition audit is saved at `outputs/experiment6/bounded-window-probe-v1/phase4-shape-audit.{json,csv}`. It binds actual request/response paths and hashes, source lengths, tile dimensions, pixel totals, finish reasons, and observed usage. Missing usage is not filled with zero.

## Fixed new scope

`scripts/prepare_bounded_visual_probe_v1.py --prepare --audit` prepared six contiguous windows: q004 development and q009 holdout, each at early/middle/late predetermined source positions. Each window is at most **512 UTF-8 bytes and 96 whitespace words**, with Unicode character boundaries and ASCII word boundaries where possible. An unavoidable split inside an opaque long token is flagged. The original substring, byte/character offsets, parent source hash, and covered message positions are retained. No window is replaced because it lacks a convenient fact or yields a bad answer.

All five planned conditions use the same exact window: text, canvas 1/.75/.5, and summary. The reconstruction output cap is 768 tokens, thinking disabled, with a request for at most 100 words. Fixed output budgets do not imply matched input token budgets. Distances are source positions/observed ages, not an experimental intervention on elapsed context or evidence of causal temporal decay.

The initial reading gate uses only text and three image scales. Facts, summary, and semantic grading remain **pending**; canvas requests are explicitly incomplete until real renderer outputs and wire proofs are bound. Up to three facts may later be extracted from each unchanged window, limited to explicitly present numbers, URLs, or entities. Fact answers and supporting quotes stay out of prediction requests. Empty fact sets are retained and reported.

The preparer stores the root config SHA and model as preparation provenance. Future consumption should verify this frozen manifest and its artifacts, not demand that unrelated root configuration remain unchanged. It refuses to overwrite a different prepared artifact.

## Evidence and limits

- Manifest: `outputs/experiment6/bounded-window-probe-v1/manifest.json`.
- Sources and request templates: `windows/<case>_<position>/` beneath that root.
- Five unit tests cover byte/word bounds, Unicode, deterministic slicing, answer-free QA construction, and fact grounding.
- Preparation made zero network and model calls. A renderer-input file contains only the chosen source text; consumers must ensure the renderer actually selects that message instead of returning an unchanged no-tool-round history.
- Local-window reconstruction, exact substring coverage, semantic factual recall, and full-history retention are distinct metrics. No new accuracy or retention result is claimed here.
