# Exact-request information-loss recovery V13

The V8/V9/V10 audit retains every physical `started.json`, including unknown responses, grouped by the exact scientific request fingerprint. Successful responses are reused even if they are length-truncated or score poorly. Existing completed conditions are not re-evaluated. The facts, questions, source text, tiles, image detail, thinking configuration, prompts, 8192 output-token limit, and same-model judge protocol remain unchanged.

All previously unsuccessful observed fingerprints have exhausted three physical sends or have uncertain acceptance. They remain blocked. The independent recovery can submit a never-issued reconstruction or its later semantic judge without reissuing an exhausted QA; these are separate measurements. It does not turn a blocked QA into a valid answer or treat zero valid judges as zero recall.

`scripts/info_loss_quota_recovery_v13.py` is dry by default. It uses the approved `network_entry_v13.py` for the replacement proxy, with a separate output namespace `outputs/experiment6/request-quota-recovery-v13`. It makes at most one new HTTP operation per eligible stage in a pass, counts previous generations and new starts toward three, does not retry unknown acceptance, and records request SHA, cumulative index, route, raw response/usage and client duration. Its HTTP limits remain below the one-hour task ceiling. Provider-internal latency and missing usage stay unknown.

The dry disposition list is frozen to disk before live execution. This recovery is not a short-window study, a changed-image protocol, or evidence that more output tokens will fix full-history reconstruction. Previously observed length/refusal/low-readability outcomes remain in the record. q004 remains development; the nine holdout cases and paired fact denominators remain unchanged.

Audit: `outputs/recovery-controlled-info-v13/audit.json`. This is operational continuation, not a claim that all 50 conditions are evaluable. Runtime status and physical HTTP ledgers, rather than live process IDs, determine actual progress.
