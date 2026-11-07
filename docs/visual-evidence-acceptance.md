# Visual evidence acceptance criteria

The 2026-11-07 audit found that successful rendering and a completed trajectory do not establish that visual memory reached the model. Corrected implementations must have their own version and preserve the original attempts and incurred usage.

For each compression event, retain three separately verified layers:

1. **Source to rendered images:** exact selected source span, original native-image ledger, renderer/settings, page count, original image bytes, decoded dimensions and SHA256. Decode every artifact; flag missing/blank pages and partial render failures. Visual inspection is sampled and is not proof that every fact is readable.
2. **Session attachments:** ordered image references, actual bytes after any resizing or format conversion, dimensions/media type/SHA256, and an explicit mapping to original render pages. Native evidence images must be independently accounted for; original crop/zoom pixels may not silently become descriptions.
3. **Actual outbound model request:** model route, image count, media type, dimensions, detail and content hash at the final transport boundary, matched to the expected images. Record transformations explicitly. Do not log credentials or headers. A session attachment reference alone is not transport proof; a lower prompt-token count is not proof either.

Hermes must positively declare the configured route as vision-capable and refuse automatic caption fallback for this experiment. A missing or substituted canvas must stop the corrected run before a paid main-model call. DSH must verify the serialized adapter request rather than relying only on native session events. Existing frozen harness implementation files are not silently patched.

Validation has two levels:

- A localhost fixture uses the real harness compression/routing/adapter stack, verifies image payload identity, then observes a tool call, its result, and a final response. It must also exercise failure cases (missing image, wrong digest, disabled vision), and not bypass routing by injecting images at the last moment.
- A bounded real model probe receives actual full compression canvases and questions about facts present in those canvases, without the answers in the prompt. Use the same model and account for every request. A timeout, no usable response, or an incorrect answer remains an unsuccessful observation. Do not substitute easier snippets and call the full canvas validated.

A passing transport audit does not establish lossless memory or benchmark accuracy. Dense and very tall canvases require explicit readability checks. Report source-image fidelity, delivered-image fidelity, and probe accuracy separately. Only restored visual routing and valid actual image inputs qualify corrected runs for subsequent RQ3 analysis; old affected Hermes/RQ3 records stay excluded from native-canvas evidence while their costs remain accounted for.
