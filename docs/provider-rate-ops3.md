# Provider rate-limit reduction and ops3 rollout

The 09:27–09:32 UTC sample on 2026-11-08 contains explicit `ModelAccountRpmRateLimitExceeded` and `ModelAccountTpmRateLimitExceeded` responses for the routed `deepseek-v4-1-flash` model. This differs from the earlier `system_memory_limit` response. The body identifies model-account RPM/TPM admission limits; retained evidence does not independently prove which physical gateway generated that body. A presumed 120 RPM account limit is an estimate, not a verified quota.

Source samples: `outputs/preflight/cloud-ops2-monitor-20261108/first-rate-limit-audit.json` and DSH discard q_059_r01's `native/discard/q_059/workspace/metrics/calls.jsonl`. In that trajectory three failures at 09:29:36–09:29:45 were followed by a successful tool-call response starting 09:29:52. Another failure at 09:32:04 was followed by success at 09:32:10. Requests continue to make progress, but the short retries do not provide global rate control.

The pinned DSH policy permits five retries after the original request, with local delays approximately 0.5, 1, 2, 4 and 8 seconds plus symmetric 10% jitter. Durable `llm/retry` events confirm this policy and reset at each new step. The inspected events do not contain `providerRetryAfterMs`. The HTTP usage observer does not persist response headers, so their absence in these events cannot establish that the server omitted `Retry-After`.

Hermes uses `agent.api_max_retries=3`, disables OpenAI SDK automatic retries, and increments its failure counter before checking that limit. For ordinary repeated rate-limit errors this means up to three failed attempts in one call block, with approximately 2–3 and 4–6 second waits before attempts two and three when no parsed Retry-After overrides them. Hermes summarize q_060_r01 failed after exactly three rate-limit errors at 09:22:21, 09:22:23 and 09:22:28; Hermes none q_069_r01 likewise terminated after three consecutive errors. These terminal failures should remain visible rather than being retried as new benchmark attempts.

The selected operational change is four active workers per cloud node and four locally, a target of 44 across ten cloud nodes plus local. It changes dispatch pressure without changing model, endpoint, tools, retry policy or scientific jobs. Its efficacy must be assessed after drain and startup; it is not a guarantee that 429s disappear. No native process should be suspended, and active requests should not be interrupted merely to change dispatch concurrency.

`scripts/roll_sco_bc_v3_rate_ops.py` implements the replacement stage only. Main supervises the explicit stop-dispatch and clean drain separately. The roller requires:

- An independently successful ops2 create receipt for each selected cell.
- ACP state exactly `SUCCEEDED`, bound bootstrap and namespace identity, controller exit zero, and durable clean-drain evidence.
- A fixed ops3 name proven absent by `trainingJobNotFound`; failed or ambiguous queries do not authorize creation.
- `configs/cloud-dispatch-ops-v2.json` explicitly selecting cloud4/local4.

The script copies the ops2 ACP argv and changes only `--job-name` and `--name` to ops3. Image, worker specification, mounts, startup command and platform allocation are unchanged. It does not invoke the unsupported ACP `start` operation. A permanent per-name receipt directory permits only one create attempt: submitted, rejected, unknown, interrupted, and incomplete receipts are never automatically repeated.

Before creating, the roller writes a namespace retirement record matching hostname, boot ID and PID namespace, plus the parent receipts, drain evidence, new source hashes and dispatch configuration hash. Request and response records live in `outputs/cloud-runtime/rate-replacements/<ops3-name>/`. Cloud query/create output uses the existing credential-redacting helpers. No credentials are added to these receipts.

```sh
# Query-only assessment; creates no cloud resource and retires no namespace.
python scripts/roll_sco_bc_v3_rate_ops.py
# Explicit authorized rollout, waiting for clean-drain evidence per cell.
python scripts/roll_sco_bc_v3_rate_ops.py --watch --live
```

Seven isolated tests cover terminal and namespace requirements, controller-only drain proof, unknown creation outcomes, exact argv preservation, retirement conflicts, permanent existing claims, read-only default behavior and ambiguous new-name queries. Implementation testing made no cloud queries, resource mutations or model calls.
