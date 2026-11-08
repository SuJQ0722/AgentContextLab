# DSH visual image omission blocked by the wire guard

The two inspected attempts encountered a local adapter image-payload limit after their second visual compression. The native `compaction-image-offload` plugin then marked the oldest image for omission. The wire guard correctly rejected the resulting incomplete image set before any HTTP request was sent. This is an image-policy integration failure, not an ordinary network failure.

| Attempt | Expected images after compression | Exact base64 image bytes | Local configured cap | Native offload decision | Images after native projection, offline replay | Unsent guard failures |
|---|---:|---:|---:|---:|---:|---:|
| DSH visual q_039_r01, attempt_001 | 6 | 24,203,284 | 20,971,520 | 1 oldest | 5 | 5 |
| DSH visual q_048_r01, attempt_001 | 4 | 21,999,488 | 20,971,520 | 1 oldest | 3 | 6 |

The 20 MiB ceiling is explicitly set in `scripts/dsh_image_preservation.py`; this audit does not establish that it is the actual TokenHub server limit. The calculation includes base64 expansion, `4 * ceil(encoded_png_bytes / 3)`, for each occurrence. q_039's six expected images include an already retained canvas as well as the five canvases in the latest compression ledger.

The native pi-ai adapter checks the aggregate size in `deepseekHarness/packages/llm/llm-pi-ai/src/context.ts` and raises `IMAGE_OFFLOAD_REQUIRED`. The still-enabled native plugin in `deepseekHarness/packages/compaction/compaction-image-offload/src/index.ts` responds by persisting `image/offload` and retrying. The immutable attachment ledger in `scripts/dsh_wire_expectations.mjs` continues to require every original image; the adapter projects the marked image to placeholder text. Accepting only the remaining images would violate the experiment's evidence-preservation requirement.

Persisted evidence:

- q_039: second compression at 09:03:29.796 UTC, `IMAGE_OFFLOAD_REQUIRED` at 09:03:31.190, then `image/offload` event seq 268 targeting message seq 263, image index 0. Five local guard failures follow; each has `request_sent=false`.
- q_048: second compression at 08:55:38.985 UTC, `IMAGE_OFFLOAD_REQUIRED` at 08:55:55.280, then `image/offload` event seq 113 targeting message seq 108, image index 0. Six local guard failures follow; each has `request_sent=false`.
- Both compression records have zero auxiliary summary calls. Earlier HTTP 429 responses were followed by successful HTTP 200 responses before the second compression. These observations do not support classifying the guard failures as direct 429 or summarization failures.

Each attempt's evidence is under `outputs/campaigns/bc100-r3-hermes-parity-v3/jobs/dsh/visual/<qid>_r01/attempts/attempt_001/native/visual_native/<qid>/`: `workspace/metrics/{calls.jsonl,shared-policy.jsonl,expected-wire.json,wire/requests.jsonl}` and the compressed `dsh-home/sessions/**/session.v4.jsonl.zstd` journal. No answers or credentials are reproduced here.

The recorded `images=[]` is not evidence that the actual request contained zero images. In the frozen wire guard, `applyExpectedImageDetails` validates the image count before `images=inspect(body)` assigns the audit variable. Its exception leaves that variable at its initial empty value. The offline replay finds five and three actual images respectively, and reproduces the misleading empty audit array. It does not claim to reconstruct an archived complete HTTP body: those rejected bodies were not saved.

Offline reproduction:

```sh
.tools/node-v24.11.0-linux-x64/bin/node scripts/check_dsh_image_offload_failure.mjs
```

The check uses the retained real PNGs, the native `toPiContext` conversion and `offloadMessageImages` projection, and the unchanged wire guard. Its final Chat Completions field conversion is a fixture; no HTTP or model calls occur. It verifies both failures and, as an offline counterfactual, verifies that supplying the complete image payload within an explicitly sufficient limit preserves all hashes and details. Results: `outputs/preflight/dsh-image-offload-diagnosis/result.json`.

The minimum repair must be a new reviewed execution version, with historical attempts and their configuration preserved:

1. Disable native image offloading for the evidence-preserving experiment. Do not filter offloaded images from the expected ledger, drop images, resize them, or weaken count/order/hash/detail checks.
2. Declare a complete-payload admission limit for the new version and verify actual gateway acceptance separately. The existing two payloads require more than 20 MiB. Exceeding a supported limit must terminate with an explicit image-budget failure, rather than silently omit evidence or repeatedly report a generic transport error.
3. Capture actual image metadata before detail validation, so a rejected request records its retained and missing images accurately. Treat deterministic guard rejection as terminal for that request.
4. Extend the local production-entry fixture to include repeated compression and aggregate images above 20 MiB, preserving all images through the final HTTP payload. The existing single-compression fixture did not cover this condition.

This audit changes no frozen scientific source, configuration, plan, live process, or existing result. It does not retry either failed attempt or validate a new production payload limit.
