# Exact-request information-loss recovery V13

The V8/V9/V10 audit retains every physical `started.json`, including unknown responses, grouped by the exact scientific request fingerprint. Successful responses are reused even if they are length-truncated or score poorly. Existing completed conditions are not re-evaluated. The facts, questions, source text, tiles, image detail, thinking configuration, prompts, 8192 output-token limit, and same-model judge protocol remain unchanged.

All previously unsuccessful observed fingerprints have exhausted three physical sends or have uncertain acceptance. They remain blocked. The independent recovery can submit a never-issued reconstruction or its later semantic judge without reissuing an exhausted QA; these are separate measurements. It does not turn a blocked QA into a valid answer or treat zero valid judges as zero recall.

`scripts/info_loss_quota_recovery_v13.py` is dry by default. It uses the approved `network_entry_v13.py` for the replacement proxy, with a separate output namespace `outputs/experiment6/request-quota-recovery-v13`. It makes at most one new HTTP operation per eligible stage in a pass, counts previous generations and new starts toward three, does not retry unknown acceptance, and records request SHA, cumulative index, route, raw response/usage and client duration. Its HTTP limits remain below the one-hour task ceiling. Provider-internal latency and missing usage stay unknown.

The dry disposition list is frozen to disk before live execution. This recovery is not a short-window study, a changed-image protocol, or evidence that more output tokens will fix full-history reconstruction. Previously observed length/refusal/low-readability outcomes remain in the record. q004 remains development; the nine holdout cases and paired fact denominators remain unchanged.

Audit: `outputs/recovery-controlled-info-v13/audit.json`. This is operational continuation, not a claim that all 50 conditions are evaluable. Runtime status and physical HTTP ledgers, rather than live process IDs, determine actual progress.

## Separate actual-output recall (authorized extension)

`scripts/info_loss_partial_output_judge_v13.py` watches only the newly produced V13 reconstruction outputs that finish with `length`. It does not request another reconstruction. These outputs remain incomplete and contribute zero reconstruction-completion credit. Their existing text can nevertheless be evaluated for supported source facts; this metric is explicitly **actual generated-output key-fact recall**, not successful full-history reconstruction.

The supplemental judge prompt is byte-for-byte the same as the original stop-response judge prompt, verified by a zero-model test against the frozen original function. Facts, model route, 8192 output cap, and disabled-thinking configuration are unchanged. Only never-issued judge requests are allowed. Main-worker stop-response judges and this sidecar's length-response judges are disjoint, so at most one judge per one of the eighteen newly authorized reconstruction requests (18 reconstruction + 18 judge ceiling). Old completed/failed judge calls are not repeated. Missing or invalid judge output remains unknown.

Separate outputs: `outputs/experiment6/request-quota-recovery-v13/partial-output-judge-v1`. All per-condition records include source-response path/SHA, finish reason, `reconstruction_complete: false`, and the separate semantic metric. Original phase4/V10 results and the running V13 reconstruction worker remain untouched.
