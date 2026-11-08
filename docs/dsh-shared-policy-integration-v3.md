# DSH integration of the Hermes context policy (v3)

This is a new experimental lineage. Old frozen campaigns remain stopped and their results/configuration are not rewritten. No paid evaluation was used for these integration checks.

## Shared policy and native history

`plugins/dsh-context/hermes-policy-v3.mjs` invokes `scripts/shared_context_policy.py`, which instantiates the actual customized Hermes five engines. Both runners use the same explicit policy configuration. The trigger is the most recent provider prompt token count, including cached input. Missing latest usage remains unknown, rather than falling back to an older response or a local estimate. Selection, protected rounds, summary prompt, summary response assembly, and visual rendering are Hermes code, not a second BasicCompaction approximation. There is no DSH-only 16k post-compression rejection in this shared-core variant. The separate controlled-baseline protocol still has its own matched budget requirement.

DSH retains its native agent loop and durable session log. Unchanged messages keep their native identities. Text-only content is canonicalized to the same string representation used by Hermes; mixed image blocks retain their position. Tool-result budget processing calls the actual Hermes helper. Changed spans are replaced individually, preserving role and tool-call pairing. A plugin-owned durable projection represents legitimate Hermes edits of retained assistant content, or an assistant-role summary attributed to the recorded auxiliary call. Restoring these sessions requires the same versioned policy plugin; generic readers without its projection interpreter cannot claim equivalent replay.

Summary calls use the exact Python-generated pending request through DSH's native LLM service. An on-disk pending journal is written before sending. A settled response can be replayed into the Python policy without another model request; an unsettled attempt blocks automatic retry. Unsupported surface edit shapes fail before live mutation rather than flattening the complete history into a user message.

## Image preservation and detail

Native evidence is resolved at its original message/content position. Visual compression uses the shared Hermes renderer's `multimodal-wrap-v2` layout for native input images, image-search evidence, crops, zooms, and tables. Selected evidence is drawn in the canvas next to its text; it is not separately appended again. Uncompressed head/tail evidence remains native. Controlled native-image baselines retain their own evidence policy.

The new provider/attachment configuration admits up to 64 million pixels, 65,535 pixels per dimension, and 50 MiB per image, while retaining the aggregate 20 MiB request-image limit. These are client admission ceilings, not a provider support guarantee. Source admission and final HTTP validation reject image transformation or omission. No tiling is enabled by default. The upstream pinned adapter supports configurable `requestImagePixelBudget`; its 4 MP constant is only a default.

Native image blocks carry `aclImageDetail`. The explicit v3 HTTP adapter, enabled by `ACL_IMAGE_WIRE_APPLY_DETAILS=1`, copies only the expected `low`/`high`/`auto` setting to each final `image_url`. Its before/after ledger is separate from the image guard; it is not described as a read-only observer. Image bytes, URL, count, and order are unchanged and verified. Without that flag, the guard remains audit-only. PNG, JPEG, WebP, and GIF geometry are checked.

## Usage and timing records

The wire observer clones the HTTP response without changing the response consumed by the SDK. It stores raw usage counters and explicit cache-field presence, never response text or headers. SSE completion/EOF, missing usage, transport failure, and conservation failures are distinguished. Cache omission remains null, including when pi-ai's normalized usage silently supplies zero. Ordinary agent and auxiliary compression calls are separated by session ID, purpose, and request ID. Stream completion and the next policy step flush the observer; pending observation cannot reuse an older count.

Each policy record separately stores subprocess/IPC wall time, each helper's engine/renderer timings, actual renderer wall time, summary request timing, and the engine compression-count delta. Nested timings must not be summed as disjoint costs. Tool-budget-only changes are not compression events. DSH local post-compression tokens are estimates. None of these client timings is mislabeled as server execution latency.

## Offline evidence

- Five actual Hermes strategies run through native DSH surface updates and persisted replay in `tests/dsh-shared-policy.test.mjs`.
- Same colorful multimodal input: `outputs/preflight/dsh-shared-matched-1794118081326564188/result.json`. Direct Hermes and DSH shared-policy/native/actual PiAi HTTP produce the identical complete canvas SHA256 `5adb1c5e3be00e303de9f51bd0ee7a5a622b69bf62b507ab0416650a84b871c0`, with identical image detail. The two HTTP calls use localhost synthetic responses and provider usage, not a paid model.
- Reviewable identical previews: [Hermes](visual-integrity/repair-v3/hermes-matched.png), [DSH](visual-integrity/repair-v3/dsh-matched.png), [manifest](visual-integrity/repair-v3/matched-canvas-manifest.json).
- This demonstrates rendering and transmission parity for the tested fixture, not semantic reading accuracy, benchmark accuracy, or identity of the two native agent loops.

New runs require a new plan/configuration hash, the shared policy plugin instead of `compaction-basic`/`tool-result-pruner`, the Hermes tool bridge instead of native `tool-web` or old `acl-local-web`, the preservation patch, and the expectation/wire/detail/raw-usage modules. `scripts/run_dsh_eval_v3.py` is the versioned entrypoint. Experiments have not been resumed by these checks.
