# Shared Hermes tools for DSH, version 2

The new opt-in DSH plugin invokes the pinned Hermes Python handlers for `web_search`, `web_extract`, `image_search`, `image_crop`, and `image_zoom_in`. The old `plugins/dsh-local-web/index.mjs`, historical experiment configs, Hermes tool-handler source, and DSH submodule are unchanged (the separate shared visual renderer is repaired in this review). No experiment or model evaluation was started during this repair.

## What is shared

[`scripts/hermes_tool_bridge.py`](../scripts/hermes_tool_bridge.py) imports the real Hermes local-web wrapper and image-tool handlers. This preserves search language selection, result order/envelopes, per-URL fetch errors, URL checks, base64 cleanup, fetch head/tail truncation, crop padding/resizing, and zoom's original local EDSR/Lanczos choice. It does not call a separate caption/model service.

[`plugins/dsh-local-web/hermes-tools-v2.mjs`](../plugins/dsh-local-web/hermes-tools-v2.mjs) registers the original Hermes tool names. It renders returned text verbatim. Crop/zoom return their real ordered text and image blocks; PNG bytes are archived, passed to `attachments.saveImages`, read back, and checked byte-for-byte. Any attachment recompression fails closed. Source path, SHA, pixel SHA, dimensions, original content index, bbox/label metadata, and DSH attachment reference remain linked in `hermes-tool-bridge.jsonl` and the canonical tool value. A text/URL result is not silently promoted to an image.

`image_search` is **reverse image search**, using the original Serper Lens endpoint `https://google.serper.dev/lens`; it is not an ordinary image keyword search and does not use the text `/search` cache proxy. Hermes returns JSON containing `thumbnail_url`, not a native image block. The bridge retains this exact behavior; thumbnail retrieval during canvas rendering is separate. Tests of crop/zoom image admission do not prove those remote thumbnails are immutable or archived. Freezing thumbnails requires recording their bytes/source URLs for both harnesses.

Both per-result persistence and per-turn aggregate budgeting reuse `tools.tool_result_storage` and `tools.budget_config`. A normal bridge call applies the same per-result threshold and preview as Hermes; multimodal results bypass this text persistence. The DSH context adapter can invoke the following IPC before the next model request to project a completed turn through the actual Hermes aggregate helper:

```json
{"operation":"tool_budget","context_length":1000000,"messages":[{"role":"tool","tool_call_id":"id","content":"result text"}]}
```

The response includes projected `messages`, input/output hashes, and `turn_budget_chars`. Raw tool events must remain recorded alongside that projection. Merely calling the per-result handler does not establish aggregate-budget parity. Hermes `tool_output.max_bytes` is read by the terminal tool, not a generic 15,000-character web cap; the web wrapper's `char_limit` and result-persistence budgets are different controls.

DSH's schema vocabulary lacks Hermes `minimum/maximum/minItems/maxItems` and `anyOf`. The adapter preserves range/length guidance in descriptions, uses `oneOf` for the disjoint scalar-or-array padding alternatives, and retains original handler validation/clamping. Model-facing schemas and malformed-argument coercion are therefore not byte-identical across harnesses. Valid-input handler semantics, returned evidence, and native image pixels are the intended parity surface; actual harness message framing still differs.

## Activation contract

Use a **new** overlay and output directory. Disable built-in entry `tool-web` to avoid duplicate `web_search` registration, and disable/remove the old `acl-local-web` plugin whose allowlist would suppress the new tools. Mount `hermes-tools-v2.mjs` with:

```json
{
  "python":"/absolute/path/to/hermes-agent/.venv/bin/python",
  "bridge":"/absolute/path/to/scripts/hermes_tool_bridge.py",
  "workspace":"/absolute/path/to/run/workspace",
  "metricsDir":"/absolute/path/to/run/workspace/metrics",
  "timeoutMs":210000,
  "maxResultBytes":16777216
}
```

The caller must set `ACL_WEB_SECRETS` through `configure_web`, `ACL_CONTEXT_WINDOW`, a run-scoped `HERMES_IMAGE_ROOT` containing admitted native image files, and attachment normalization to **preserve**. Do not set a narrower competing tool allowlist. The plugin restricts tools at **agent creation**, before the first request's tool snapshot; a pre-step-only restriction was too late and exposed unrelated built-in tools on the first request. The plugin admits only the five named tools; there is no misleading `web_fetch` alias with DSH's old schema. Credentials stay in the environment or a run-private 0600 Hermes config, never the overlay. Python bridge startup also normalizes DSH's bracketed IPv6 `NO_PROXY` entry `[::1]` to `::1`; the former makes httpx reject otherwise valid search/fetch requests.

The bridge is deliberately **text-mode Reader only** during this no-model workflow. A markdown fetch request is rejected before dispatch because the original Reader's markdown mode may invoke an LLM. Image crop/zoom are local image operations, not model calls. IPC cancellation terminates the Python child, and the timeout/output-byte cap prevents an unbounded subprocess. `web-starts.jsonl` plus `web.jsonl` distinguish unfinished requests from completed ones. Cache headers missing from a response remain unknown; HTTP success is not automatically tool/content success or source-origin HTTP status.

## Actual network checks

Evidence is under `outputs/preflight/hermes-tool-bridge-v2/`:

| Check | Measured result |
|---|---|
| Original Serper text search | Earlier audit: a new DSH query cache miss followed by Hermes cache hit, identical three-result content; see `outputs/web-endpoint-audit-2026-11-08/fresh-search/` |
| Real shared `image_search` handler, public Unsplash image URL | `live-lens.json`: success, three nonempty Lens results, handler 7.90 seconds; no model inference |
| Old Reader `10.13.64.17:8080` | New direct POST `/fetch` timed out after 30 seconds; `/docs` and `/openapi.json` timed out after 8 seconds. Earlier 180-second request also timed out. The remote service is **not repaired** |
| New local same-source text Reader | `local-reader-verification.json`: example.com returned 156 chars in 2.06 seconds; historical failing WordPress page returned 12,190 chars in 2.08 seconds; both HTTP 200/success=true |
| Actual Hermes `web_extract` wrapper via bridge against new local Reader | `live-bridge-reader.json`: same two URLs returned 156 / 12,190 chars with null error |
| Model-mode rejection | New Reader rejects markdown/LLM fields with HTTP 400; the bridge independently rejects markdown before dispatch |

The upload key was found in the original project's `hermes-agent/.env.local`, then copied **only as IMAGE_UPLOAD_API_KEY** into the current ignored, mode-0600 `hermes-agent/.env.local`. `configure_web` shares only that key with both harnesses; unrelated Hermes provider credentials are not imported into DSH. Explicit environment values take precedence. The key and upload URL are not included in committed evidence.

[Real synthetic-crop upload validation](visual-integrity/repair-v3/imgbb-crop-validation.json) passed: actual crop handler → imgBB upload → Serper Lens. Uploaded bytes matched the crop SHA and differed from the parent SHA. Lens returned success with zero matches for this synthetic image; this proves the local-image service route, not image-search accuracy. No model calls.

The bridge also supports an optional `ACL_IMAGE_ORIGIN_MAP` pointing to a caller-owned JSON ledger:

```json
{"images":[{"path":"/run/input/original.png","sha256":"downloaded-byte-hash","origin_url":"https://public.example/original.png","kind":"native_original","transformed":false}]}
```

Only an allowed local path with matching bytes and `native_original` is resolved to that URL. Changed files fail; unknown files use the real configured upload backend. A crop/zoom output is never automatically mapped to its parent image URL. The same optional resolver must be applied in both new runners if enabled. The synthetic-crop validation independently exercises local upload; public-URL Lens results alone are not used as its evidence. A public URL can also change after download; its archive hash documents local evidence but cannot force the external Lens service to retrieve historic bytes.

## Local Reader bootstrap and limits

[`scripts/local_reader_text_service.py`](../scripts/local_reader_text_service.py) uses the existing shared ReaderEngine at `/mnt/afs_agents/pangcong/workspace/projects/fetch_server/server.py`, pinned by [`configs/reader-text-v1.json`](../configs/reader-text-v1.json) to SHA-256 `fd90a4ef57ef775e5bb48b25d2cb81c517f9ef2601b8be03efe5ef67d17dd743`. It does not read that owner's config or credentials. The model summary method is blocked, only explicit text-mode POST `/fetch` is exposed, and binding is restricted to loopback. Our Jina key remains request-scoped.

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u http_proxy -u https_proxy -u all_proxy \
  /opt/conda/bin/python scripts/local_reader_text_service.py --config configs/reader-text-v1.json
```

The current tested service process is PID 89991, endpoint `http://127.0.0.1:18080`, recorded with `/proc` start identity in `reader-process.json`; earlier process records remain in the history. This is a reversible local repair process, not an SCO instance or resumed experiment. The public config bounds extraction to one process and four concurrent fetches. The service, multiprocessing resource tracker, and extraction child must count against the global visible-process limit. A future host requires its own loopback service; this endpoint cannot serve a different machine's loopback.

The tested Python runtime has httpx 0.28.1, uvicorn 0.40.0, fastapi 0.128.0, pydantic 2.12.3, PyYAML 6.0.3, tiktoken 0.12.0, trafilatura 2.1.0, and fetch_url_package 1.6.0. Exact versions are recorded in `reader-dependencies.json`. These dependencies are present in `/opt/conda/bin/python`, not the Hermes venv. The shared AFS source is an explicit deployment dependency; startup refuses a changed hash rather than silently importing a new implementation. No third-party config or credential file was copied. The local service uses the shared engine's text extraction/cache/Jina fallback behavior; successful HTML retrieval does not imply every PDF/site or Jina fallback path has been tested.

The wrapper now observes the existing `content_cache.get` return and `fetch_async`'s `metadata.from_cache`, without an extra lookup or altered cache policy. Per-request `ContextVar` state prevents concurrent calls from sharing a hit value. `X-Cached` is emitted only for a successful final primary HTML result with observed hit/miss evidence; Jina fallback, missing evidence, and failed final extraction leave it absent. `X-ACL-Cache-Layer=fetch_url_package.content_cache` identifies the layer, `X-ACL-Fetch-Backend` identifies the final source, and `X-ACL-Primary-Cache` separately reports a known primary lookup even if later fallback occurred. Bridge metrics preserve these fields. These are **web content-cache** statistics, separate from provider cached input tokens.

`reader-cache-observed-lookup.json` records a real cold request followed by a repeat: `X-Cached: false` then `true`, identical 156-character body SHA, 2.351 seconds and 0.00587 seconds. Header truth comes from actual cache operations, not latency. The earlier metadata-only observation is retained in `reader-cache-verification.json`; it left the first miss unknown because the upstream fresh-result metadata omits `from_cache`. Three cache-observer unit tests cover concurrent isolation, missing values, Jina fallback, extraction failure, and exact-once cache lookup.

## Reproducible verification

```bash
python -m unittest discover -s tests -p test_hermes_tool_bridge.py -v
.tools/node-v24.11.0-linux-x64/bin/node --test scripts/test_hermes_tools_bridge.mjs
```

The Python suite covers real crop/zoom geometry and identical image bytes, invalid bbox/path behavior, real web wrapper language/envelope/head-tail behavior under injected transport, rejection of Reader model mode, shared spill budgeting, verified-original URL mapping, and DSH/Python IPv6 proxy compatibility. Three Node tests pass: ordered native admission including duplicates, rejection of changed source/stored bytes, actual DSH tool definition rendering and argument schema, and child cancellation. These tests make no external network/model calls. The native DSH loop/compaction/final-HTTP fixture is owned by the context adapter validation and must be reported separately; these unit tests do not substitute for it.

## Review of the new runner entrypoints

The independent entrypoint review fixed relative output/config paths in `run_dsh_eval_v3.py`, set its run-specific image root/cache explicitly, and added final resolved web checks after environment overrides. Offline fixture settings now require loopback model/web endpoints and explicit Reader text mode. Five review-guard tests pass, including rejection of an environment override that would replace a loopback fetch service with a remote endpoint.

Both new entrypoints atomically claim an attempt before tool/model work and reject incomplete existing claims. DSH skips an existing terminal result only when repeat, model, config hash, and cohort hash match; callers must use a distinct output root for a different repeat/config. These are fresh-attempt runners, not native-session continuation. Interrupted or unknown attempts require inspection and an explicit new attempt directory, preventing silent duplicate charges.

`entrypoint-review.json` records actual command-level checks: both dry-run commands expose precisely the five intended tool names; both live commands fail on the user's pause gate before model initialization/child launch. No model call occurred. The DSH runner's replacement of its old context plugin with the shared policy and each harness's final request-level image/text parity are separate integration checks; dry-run tool lists alone do not establish them.

## Actual production DSH entrypoint acceptance (2026-11-08)

`python scripts/check_dsh_v3_entry.py` completed successfully through the real `run_dsh_eval_v3.py` CLI. Evidence: `outputs/preflight/dsh-v3-entry-1794118218199626279/result.json` (`passed=true`). This fresh process run used the frozen implementations; nine runner/policy/helper/tool/wire implementation hashes were unchanged before and after each strategy. Earlier failed development attempts remain separate evidence and are not included as passing runs.

| Check | `none` | `visual_native` |
|---|---|---|
| Real CLI completed | Yes | Yes |
| Actual localhost model HTTP requests | 5 | 5 |
| Tool schemas on every request | Exactly search, extract, Lens, crop, zoom | Same five |
| Actual tool execution | Search, extract, crop, zoom | Search, extract, crop, zoom |
| Local mock reports 40,000 prompt tokens | Preserved without compression | Triggers the unchanged 32,768-token threshold |
| New shared-policy canvas on actual HTTP wire | None, as expected | Present; every new canvas source SHA found on wire |
| Final image detail, expected and actual | `auto`, `auto` | `high`, `auto` |
| Wire guard errors | 0 | 0 |

The final visual canvas SHA is `3f4bcdfae148ef81bc57cd924b2024ff057c20327b68bb6ef03b9510324ca2cc`. The test records actual request JSON, native image expectations, shared Python policy records, and tool image archives. Crop/zoom images are admitted through the real DSH attachment path; the canvas comes from the real shared compression renderer, not an image inserted at the final HTTP boundary. Lens schema is checked in this fixture; its real public-URL execution is the separate `live-lens.json` measurement above.

This is a synthetic localhost integration check with **zero paid model calls and zero external HTTP requests**, not benchmark accuracy or a model-vision semantic score. The fixture keeps review approval false and uses the explicit preflight-only offline exception; experiments remain paused. Production evaluation was not resumed. The old remote Reader remains unresolved; the explicit same-source local text Reader is the tested replacement. Arbitrary local crops still require a public upload backend for Lens.
