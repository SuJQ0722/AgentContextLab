# Inline image transport: engineering repair and measurements

Date: 2026-11-11 UTC. Scope: source changes and offline validation; no paid model calls and no mutation of frozen V7 experiments. Compression images remain inline data URLs. This patch has **not** been deployed into the already-running V7 containers; their outcome and latency must not be attributed to this patch.

## Repairs

- Hermes previously buffered each route until HTTP EOF, even after the provider's terminal SSE event. Both the buffered four-route path and legacy observed stream now stop at a complete `[DONE]` SSE event and close the upstream response. DSH's substring/tail matching is replaced with equivalent event framing. Split chunks, CRLF/LF/CR, quoted `data: [DONE]`, and long trailing chunks are covered.
- A truncated SSE stream without a terminal event is a transport failure. Retry buffers remain separate, so a failed partial answer cannot be concatenated with the next route's answer. Known usage from each failed attempt remains in the ledger; missing usage remains unknown. Terminal events preserve the preceding usage frame. Client timing is not provider execution time.
- DSH's authorized last-ten retention now runs before the native SDK reads/encodes attachments. The expected-image guard derives its hashes and detail fields from that same request projection. This changes neither durable history nor retained pixels/text/order. Native automatic offload is disabled in the two-hour inline worker, so it cannot silently discard additional evidence. A genuinely oversized retained set still fails; the 20 MiB SDK image budget and 32 MiB wire-body guard are unchanged.
- The two-hour DSH provider's native retry count is zero. The existing four-route loop owns network retries and still rotates through the four authorized routes until the existing task deadline. Per-container concurrency, request deadline, output budget, and model are unchanged. Deterministic local failures no longer incur five extra provider retries.
- DSH renderer image preparation reuses verified data URLs by immutable SHA-256 attachment identity. The cache is scoped to the attachment store and bounded to 16 MiB of ASCII payload; LRU eviction and oversized-entry bypass are tested. Initial bytes must match their claimed identity. Store isolation and cancellation are preserved. This is a **client encoding cache**, not provider prefix/KV caching and not a cached-input billing measurement.

## Measured image-preparation costs

Source: ten saved V7 compression WebP occurrences, eight unique byte identities, 5,303,020 raw bytes and 7,070,938 data-URL bytes. These are real saved artifacts, not a claim that all ten appeared together in one historical request. Thirty samples per operation, rotated execution order, warm filesystem cache. No model, hosting, or external network requests.

| Local operation | Median ms | p95 ms |
|---|---:|---:|
| Read file paths, then base64 encode | 21.937 | 27.130 |
| Encode already-resident image bytes | 3.245 | 5.335 |
| Retrieve verified data URLs from implemented cache | 0.026 | 0.049 |
| Reuse existing in-memory data URL array | 0.001 | 0.003 |
| JSON serialization alone | 6.537 | 9.182 |

Initial verified cache fill took 20.414 ms and eight attachment reads. Subsequent benchmark cache hits needed no additional reads. Preparation operations exclude JSON serialization, image rendering, network transmission, and provider computation. Base64 grows binary data to roughly 4/3 its original byte length; encoding cache hits do not reduce request bytes or provider token charges. See [raw measurements](inline-engineering-2026-11-11/image-preparation-benchmark.json).

For the current remote API, a client-side file path is not accessible to the provider. A wrapper accepting a path must still read and send its contents unless the service explicitly supports a shared filesystem or server-side file identifiers. Reusing an inline data URL is therefore the appropriate local optimization; sending a path string alone is not an equivalent visual input.

## Real DSH failure replay

V7 `q_048_r01` saved 34 image occurrences in the expected-wire manifest. Offline replay through the pinned native `toPiContext` with the repaired pre-SDK projection retained the last ten, read ten attachments, and matched every retained image hash and detail field at the wire guard. The original message history remained unchanged. No increased image budget, resizing, hosting, or network call was used. See [replay record](inline-engineering-2026-11-11/dsh-q048-native-replay.json).

An additional diagnostic on an older pre-V7 q048 snapshot still exceeded the existing 20 MiB image budget with only four legacy oversized PNGs (20.98 MiB base64). This is intentionally not made successful by weakening the budget: image count alone is insufficient to bound payload size. It is distinct from the V7 bounded-page replay above.

## Upstream references and applicability

- [OpenAI Python SDK stream implementation](https://github.com/openai/openai-python/blob/main/src/openai/_streaming.py): explicit terminal SSE handling and response cleanup. We apply event-aware completion to our custom buffering layer; upgrading a downstream SDK alone would not remove that layer's wait for EOF.
- [LiteLLM retries, fallbacks and cooldowns](https://docs.litellm.ai/docs/router/learn/reliability): a single router owns retries with provider SDK retries disabled. We use single-layer retry ownership, retaining the user's explicit four-route policy. A new cross-worker cooldown is not introduced.
- [vLLM multimodal inputs](https://docs.vllm.ai/en/latest/features/multimodal_inputs/): server-authorized local media paths and UUID-based media cache reuse. Those can eliminate repeated transmission when the inference service supports them. They cannot be assumed to work through the current remote TokenHub gateway; no unsupported file paths/UUID-only requests are sent.

These are mature engineering techniques, not evidence of universally optimal performance. Our local preparation benchmark is not an end-to-end speedup claim.

## Validation and remaining boundary

Regression coverage includes real local HTTP servers that send terminal SSE without closing the HTTP stream, premature EOF with route fallback and usage accounting, all split boundaries, image-cache integrity/eviction, pre-SDK retention and history restoration, plus native SDK replay of a real V7 failure. The root suite passed: `NODE_OPTIONS=--preserve-symlinks python -m unittest discover -s tests -v` — 985 tests in 150.423 seconds. The symlink flag is required by this isolated worktree's existing DSH installation. Real local HTTP terminal-event checks also passed for both languages.

Previous timeout analysis found median failed-request time of about 74 minutes for Hermes and 83 minutes for DSH, versus tens of seconds of rendering. That observational evidence identifies transport/retry waits as the dominant measured component; it does not prove every historical wait was caused by the terminal-event bug. New end-to-end timing and timeout rates require a separately frozen rollout/recovery cohort. Existing successful and failed traces must be preserved and versioned, and all failed-attempt costs retained.
