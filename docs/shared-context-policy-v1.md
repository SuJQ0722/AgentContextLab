# Shared Hermes context-policy adapter

`scripts/shared_context_policy.py` is the new `hermes-shared-context-v1` JSON interface. It directly imports the repository's Hermes `DiscardEngine`, `SlidingWindowEngine`, `SummarizeEngine` and `VisualEngine`; it does not approximate their policies in JavaScript. `none` returns the original message sequence with compression disabled. It never calls a model API.

The new Hermes entrypoint uses `context_config(strategy, experiment_config, save_dir)` to build its context configuration and `configure_engine(engine, strategy, policy_config(...))` after engine construction. The DSH adapter uses the same settings and Python implementation while preserving the returned individual system/user/assistant/tool messages in its native surface. Both paths retain the original Hermes protected-prefix, tail, pruning, summary prompt and visual-history rules. No new common post-compression token budget is introduced by this module.

## Request and response

Provide one JSON object on stdin:

```json
{
  "strategy": "discard",
  "operation": "apply",
  "config": {
    "model": "the-frozen-campaign-model",
    "context_length": 262144,
    "provider": "custom",
    "api_mode": "chat_completions",
    "threshold_tokens": 32768,
    "max_compressions": null,
    "strategy_config": {"keep_rounds": 0}
  },
  "messages": [{"role": "user", "content": "Original task", "_dsh_original_id": "source-id"}],
  "provider_usage": {"prompt_tokens": 40000, "completion_tokens": 20},
  "state": null
}
```

`operation="check"` updates observed usage and reports the threshold decision without applying compression. `apply` returns `messages`, `state`, `compression_triggered`, `changed`, and a status: `unchanged`, `compressed`, `awaiting_usage`, or `awaiting_summary`. Missing measured prompt usage remains `awaiting_usage`; the adapter does not silently substitute a local token estimate. `none` remains an identity operation even when usage is missing. Cache-read/cache-write accounting must be normalized by the host so `prompt_tokens` includes total provider input; raw and missing usage remain in the host's accounting records.

Top-level `timings` separately reports `policy_total_seconds`, `engine_seconds`, `renderer_seconds` and `renderer_calls`. Renderer time wraps the real `render_visual_compression` function and includes its local PDF/raster/image-file work (and any image fetch performed by that function). It is nested within engine time, which is nested within local policy time: do not add these overlapping quantities. The host separately measures subprocess/IPC wall time and summary model-call time. Pending summary requests, replay and engine errors retain local timing; no API latency or token usage is inferred from these durations. Timings do not enter engine state, message output or pending-request hashes.

Original message metadata such as `_dsh_original_id` remains when the actual Hermes engine retains/copies that message. Newly generated summary or canvas messages naturally lack original IDs. Hosts must compare content when reusing a retained ID: sliding-window and summary policies may modify a message's content while retaining other metadata. Do not flatten transformed messages into one user message.

Explicit `developer` messages are accepted and passed to the actual Hermes engines without relabelling them as user/system text. Their retention follows that engine's real policy: for example, discard intentionally keeps only its configured system/task/tail, whereas sliding-window preserves non-tool messages. Accepting a role does not invent additional protection for it.

State includes compression counters, previous summary, cumulative visual history, visual accounting, last observed token counters, and summary compression limit. The summary failure cooldown is stored as a UTC deadline and restored against the new process's monotonic clock; expired cooldowns normalize to zero. State is bound to the strategy, exact configuration hash and implementation-file hashes. Changed implementations/configurations require a new lineage, not silent continuation of old state. The host must atomically persist messages and matching returned state, with its own durable content hashes/transaction identity.

## Transactional summaries

When the actual Hermes summarizer reaches `auxiliary_client.call_llm`, the adapter intercepts the call before network access and returns `awaiting_summary`:

- `pending_call` contains the exact Hermes `task`, `messages`, `max_tokens`, routed model/provider/API mode, transaction hash and request hash.
- Original messages and uncommitted pre-compression state are returned. No pruned intermediate history is committed.
- The host executes this one auxiliary request through its instrumented, same-model route and records usage/cache/timing/errors normally.
- Replay the same request and returned pre-state with `summary_response={request_sha256, content, usage, call_id}`. The generated request hash must match before the supplied content is consumed.
- An explicit `summary_response.error` follows the original Hermes summary-failure behavior and retains the host's failure/unknown-usage record. Missing usage is not fabricated as zero. No automatic extra API attempt occurs in Python.

The request hash binds the original messages, configuration, state, provider usage, implementation and focus topic. A response from another source span or summary generation cannot be silently inserted. Do not repeat a host call after an uncertain response; preserve the pending transaction and missing usage for audit.

## Rendering and tool budgets

Visual configuration installs the existing `rq3-pdf-bounded-memory-v1` adapter in both paths, and its source hash participates in state binding. Ordinary PDFs still use the original converter. Large pages use the verified same-DPI Poppler conversion and exact crop predicate with bounded working arrays; no tiling, scale or typography change is introduced. The returned `pdf_adapter` metadata identifies this implementation.

The visual renderer reports `multimodal-wrap-v2`, per-occurrence native evidence provenance and source coverage. Render estimates remain distinct from measured provider image/token usage. The five-policy adapter does not modify native-image baseline variants, which require separate explicit controls.

Tool-size policy is a separate phase before inference: the new Hermes tool bridge directly reuses Hermes per-result persistence and `enforce_turn_budget` for the completed tool batch. That phase must persist the updated tool messages before the compression decision; it must also run on turns that do not compress. Its budget derives from the actual context-window configuration, rather than an independently invented DSH truncation rule.

## Validation and remaining boundary

`tests/test_shared_context_policy.py` checks provider-threshold boundaries, missing usage, exact direct-engine outputs, state/config mismatch refusal, exact summary prompts/assembly, stale summary rejection, explicit failure behavior, and expired-cooldown replay.

`scripts/check_shared_context_policy.py` performs five strategies × two compressions with a fresh subprocess for every shared-policy call. It compares full output messages against a retained direct Hermes engine instance, plus visual accumulated history/accounting and the second summary's prior-summary content. No model API is used: summary transport is replaced at the auxiliary boundary with a recorded fixture answer. The native DSH surface rewrite, tool-ID translation, final provider body, and instrumented real summary transport must each pass their own integration validation before asserting end-to-end equivalence.
