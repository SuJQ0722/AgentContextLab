# Paused experiment inspection — 2026-11-08

The user explicitly requested a pause. No model inference or evaluation was started. Existing core/RQ3 STOP markers were retained/written, an explicit pause manifest was saved, and the waiting judge process was stopped. Read-only monitoring may remain active. Successful diagnostics do not authorize experiment resumption.

## 1. Fetch endpoint and actual web-provider checks

Testing around04:37–04:42 UTC used the configured Serper and Reader protocols. Initial standalone HTTP health checks encountered a local missing SOCKS dependency; private-network health checks were then repeated with proxies explicitly bypassed. That client-side error is distinct from the subsequent direct timeouts.

- `10.13.64.17:8080`: TCP connected in17ms. Direct HTTP health/root checks timed out. Both real harness providers failed to fetch both example.com and a previously failing WordPress URL with a30s diagnostic limit; no HTTP response/body arrived. One additional real DSH fetch using180s also timed out at180.025s. The service is **not currently usable for the tested fetch requests**; server-side cause is unknown.
- Previously preferred backup `10.120.7.221:8080`: TCP and real fetch both rejected with connection refused.
- Serper `10.120.4.249:80`: both providers returned the same nonempty search results. A fresh natural-language query produced HTTP200/cache-miss through DSH (1.61s), then HTTP200/cache-hit through Hermes (0.284s). This verifies one current fresh lookup and shared cache reuse, not only old cached answers.
- Current loaded fetch setting is `extractMode=text`; these client requests included no LLM fields. Backend-internal cost is not exposed. No agent model inference was performed.

Raw results: `outputs/web-endpoint-audit-2026-11-08/summary.json` and `README.md`.

## 2. DSH web implementation parity

DSH reimplements the same Serper/Reader backend protocol, but does not execute the same complete Hermes tool wrapper. Query batching/merging, response envelopes, truncation and error semantics differ. The active DSH web restriction exposes only `web_search`/`web_fetch`, not Hermes's image search/crop/zoom/vision tools. The original Hermes BC worker is also web-only; the separate multimodal capture worker enables vision tools.

See [web implementation comparison](web-parity-audit-2026-11-08.md).

## 3. Compression images and multimodal layout

Existing saved-image integrity checks remain valid: audited DSH43 attachments and Hermes138 final PNGs decode, but native normalization and old delivery faults prevent a blanket claim of equivalent, lossless visual memory. See [image audit](visual-integrity-audit.md) and [versioned repair status](visual-integrity/status.md).

A new zero-API same-source fixture exercised real Hermes VisualEngine compression and real DSH `separateImages` plus render bridge. It put the native image inside the compressed tool-history span; the protected head and retained tail did not contain that image. The PNGs were opened and visually inspected.

| Input path | Canvas native-image layout | Native-image retention in this fixture |
|---|---|---|
| Hermes local image path | Image at right, text wraps around it | Image appears as a rendered thumbnail |
| Hermes inline data URL inside compressed history | No image drawn into canvas | Not separately retained in the compressed result |
| DSH native attachment | Text placeholder in canvas; no native-image wrapping | Original attachment reference retained separately |

A table with the renderer's supported CSV/tool-source cues renders with text wrapping in both paths. An arbitrary pipe table does not necessarily trigger this feature. Therefore sharing the PDF renderer does **not** establish matching multimodal canvases.

See [same-source rendering evidence](multimodal-render-parity-2026-11-08.md). No frozen harness, model or experiment configuration was changed. Experiments remain paused pending explicit user resumption; these findings are not automatically patched into existing scientific runs.
