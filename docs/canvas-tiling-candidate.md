# Optional full-content canvas tiling candidate

`scripts/tile_rendered_canvases.py` implements `canvas-vertical-tiles-v1`, an **offline candidate layout**. It is not enabled in any production experiment and makes no model calls. Earlier full/short probes had ambiguity between passengers and all people and did not sufficiently identify the historical source; those answers do not establish a need for tiling. A separately clarified full-canvas probe is evaluated independently.

The utility takes ordered images explicitly labelled `rendered_canvas` or `native_evidence`. Only rendered canvases are cut vertically. Each PNG tile retains the full source width and at most 1536 rows, with 32 rows of overlap by default. There is no resizing, filtering, text extraction or omitted source region. Original files are also copied byte-for-byte. Native evidence is copied unchanged as one file regardless of height and is never tiled. Callers must classify image provenance correctly; the utility cannot infer native versus rendered evidence from pixels.

The manifest records source paths, original encoded-file hashes, decoded RGBA8 pixel hashes, tile coordinates, order and file/pixel hashes. Its verification independently opens the files, checks each tile against its corresponding full source rectangle including overlaps, proves coverage of every source row, and reconstructs an image with identical decoded RGBA8 pixels. PNG RGB/RGBA/L/LA/palette sources are supported; animated and higher-bit-depth sources are rejected. The original file copy retains its original mode and bytes. Tile PNGs use RGBA8. This proves pixel preservation, not text legibility, semantic recall, or provider-side retention.

Input format:

```json
{"images": [
  {"id": "history-1", "kind": "rendered_canvas", "path": "history.png"},
  {"id": "retrieved-1", "kind": "native_evidence", "path": "retrieved.jpg"}
]}
```

Paths are relative to the spec file. Generate a new artifact directory and verify it:

```bash
python scripts/tile_rendered_canvases.py --spec spec.json --out outputs/layout-candidate
python scripts/tile_rendered_canvases.py --verify outputs/layout-candidate/manifest.json
```

Existing output directories are refused rather than overwritten. To construct a later request, traverse `images` in manifest order, then each image's `output_files` in order. Retain the source-image association and tile coordinates when evaluating reading order; the manifest itself is not an API request. Any provider normalization or transmission still needs its own byte/pixel ledger.

Offline fixtures are under `outputs/visual-integrity-audit/tiling-candidates-v1/`:

- `hermes-full3/manifest.json`: all three original PNG canvases of the archived full Hermes wire probe, in old-page then recent-page order.
- `dsh-reconstructed-full4/manifest.json`: all four offline reconstructed q001 canvases. The first three source pages match their persisted historical PNG bytes; page four is reconstructed pre-normalization PNG, not the historical normalized JPEG. See [the integrity audit](visual-integrity-audit.md).

This layout changes image count, total overlapping pixels, context accounting, cache behavior and potentially latency/cost. It must be versioned and measured independently if used in an experiment; do not pool it into the frozen original layout or claim matched budgets automatically. No accuracy or semantic-readability improvement has been measured by this utility.

Tests cover one-row sources, exact tile boundaries, one-row overflow, multi-page tall images, alpha pixels, overlap coverage, native-image byte preservation, tampered coordinates/pixels and refusal to overwrite outputs.
