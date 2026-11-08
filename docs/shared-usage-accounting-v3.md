# Raw provider usage observation for DSH

The pinned SDK loses the distinction between missing cache counters and explicit zero. In `@earendil-works/pi-ai` 1.3.0, `dist/api/openai-completions.js` initializes missing prompt tokens with `|| 0` and selects cache-read aliases with a final `?? 0` (lines 1174–1176). DSH's `packages/llm/llm-pi-ai/src/stream.ts` then emits cache fields only when their normalized value is positive. Historical normalized zero therefore does **not** prove that the provider reported zero cache hits. This observation does not repair historical logs without raw responses.

`scripts/dsh_raw_usage_observer.mjs` observes a cloned HTTP response before SDK conversion. It supports OpenAI chat JSON and SSE, including the final usage chunk. The original response and its bytes are returned unchanged. Observation runs concurrently; the fetch wrapper must not await the entire response before returning it to the SDK.

Each request records an initial response marker and a final accounting record. The final record includes the request ID, session, purpose, numeric provider usage tree, prompt/output/total counts, cache field presence, observed cache counts, non-cache derivation, and consistency checks. Provider text, request headers, credentials, and response content are not stored. Non-counter string values inside usage are omitted explicitly. Multiple SSE usage snapshots are **not summed**; the last observed usage object is retained.

Missing cached input stays `null`, with `cached_input_presence=false`. Explicit zero stays `0`, with presence true. Non-cache input is either the explicit provider miss count, or provider prompt minus explicit cache-read count. It stays unknown if neither split can be established. Cache-write counts, when supplied, are also recorded separately; “non-cache” here means the portion not reported as cache-read. Invalid counts, conflicting aliases, cache counts exceeding prompt, or inconsistent totals fail the relevant accounting checks.

SSE without `[DONE]`, malformed data, observer interruption, and transport errors have explicit statuses. Partial usage remains partial; a response with no usage does not become a zero-token response. HTTP status and body completion are separate: completion of an HTTP error body does not imply a successful inference.

The native request lifecycle must await `flushUsageObservers` after the model stream settles, including the final request of a process. Waiting only at the next agent step is insufficient. A flush timeout returns pending request IDs; it must not silently substitute an older response for the latest trigger. `latestRawUsage` orders records by request observation sequence, not completion time. Trigger matching must restrict to the same session and `purpose=agent`; compaction calls are separately attributable. The observer does not measure provider API latency.

Local validation: six Node tests cover JSON, SSE split across arbitrary chunks, missing versus explicit-zero cache, provider aliases, inconsistent counts, EOF without usage, stream interruption, pending flush, transport failures, exclusion of private response text, and byte-identical original consumption. No provider calls were made. Test file: `tests/dsh-raw-usage.test.mjs`.

Observer source SHA-256: `f09a4c64472e2c2d23538ea1059797d93aafdfeda3f54bd89c16ca7d241c5891`.
