# Routes2 claim-publication maintenance (io3)

The frozen routes1/routes2 files remain unchanged. New operational entries are `bc_claim_publication_io3.py`, `run_bc_campaign_v3_routes2_io3.py`, and `run_bc_trial_v3_routes2_io3.py`. The DSH native operational entry is `run_dsh_eval_v3_routes2_io3.py`; it adds the CLI end-of-options separator before the unchanged question, including questions beginning with a hyphen.

A sibling claim directory can become visible before its atomic `owner.json` publication. Only `FileNotFoundError` for an exact sibling claim-owner path becomes `ClaimPublicationPending`. A controller leaves the pair pending; it never interprets an unpublished owner as a legacy claim. A trial waits at most the declared finite metadata delay schedule per lookup, then preserves the unstarted claim if the owner still cannot be read. Conflicting ownership, malformed JSON, changed plans and other missing files remain errors. No model request is retried by this maintenance layer.

Original scientific validation, route-plan checks, slot ownership and the exclusive `worker-started.json` creation remain in the original trial. Frozen routes2 `prepare_runtime` and its implementation hashes are unchanged. An independent `claim-publication-io3.json` records the operational source hashes and DSH CLI override; the trial verifies it before native launch, and the DSH entry verifies its own hash and records the sidecar in its manifest.

Unexpected scheduling exceptions stop future dispatch and wait for all tracked children to finish under their original budgets before the controller exits with the failure. The drain path sends no signals to native workers. Controller failure while holding a not-yet-started reservation remains explicit and does not silently recycle that scientific claim.

## Explicit never-started recovery

The controller accepts `--unstarted-recovery-manifest PATH`. A manifest must use this structure:

```json
{
  "version": "bc-v3-unstarted-recovery-manifest-io3",
  "campaign_root": "/absolute/campaign",
  "plan_sha256": "<frozen scientific plan SHA>",
  "route_plan_sha256": "<bound routes2 SHA>",
  "entries": [{
    "job_id": "hermes/summarize/q_001_r02",
    "spec_path": "/absolute/original/spec.json",
    "attempt_path": "/absolute/original/attempts/attempt_001",
    "authorization_path": "/absolute/recovery-authorization.json",
    "authorization_sha256": "<authorization file SHA>"
  }]
}
```

Each cell authorization uses `version: bc-v3-never-started-recovery-batch-v1`, top-level `terminated_namespace_evidence_path` and `terminated_namespace_evidence_sha256`, plus `entries` containing `job_id`, `attempt_path`, `spec_sha256`, `claim_owner_sha256`, and `slot_owner_sha256`. The trial receives the same file through `--recovery-authorization` and selects its own job exactly once.

The namespace evidence must use `schema: acp-terminated-namespace-v1`, `platform_state: FAILED`, `namespace_terminated: true`, and the original claim's `hostname`, `boot_id`, `pid_namespace`, plus `name` and `uid`. It must reference `describe_path`/`describe_sha256`, `bootstrap_path`/`bootstrap_sha256`, and `exit_path`/`exit_sha256`. The gate reads those exact artifacts: ACP must report workspace `rl`, state `FAILED`, matching name and UID; the hostname must belong to that UID; bootstrap must identify the original namespace; the same cell's bootstrap exit must report controller exit code 1 after its start. A normalized boolean alone is insufficient proof.

The original spec, scientific claim, slot owner and attempt location must match their supplied hashes and ownership fields. Any `worker-started`, command, running, heartbeat, terminal result, native directory, API directory or other unrecognized attempt artifact disqualifies recovery. Only known pre-start metadata and the operational audit files are permitted. The main operator separately supplies the reviewed candidate list and repeated inventory evidence; there is no automatic discovery or blanket retry of all claims from a failed node.

Recoveries retain the original claim and slot. They enter the same controller pool before ordinary pending work; both share the total concurrency and per-route caps (for example total16, original1, sfb15). A separate exclusive recovery-dispatch marker prevents duplicate recovery dispatch. A consumed marker is not silently recycled if a later launcher fails. The original worker-started exclusive guard remains the final protection against a duplicate native launch. Already started or terminal entries are never requeued.

Offline tests cover real delayed owner-file publication, bounded waiting, malformed/conflicting-owner rejection, actual official termination evidence validation, started-evidence rejection, preservation of existing route lineage, refusal of a second native delegation, shared recovery/pending capacity, and waiting for tracked children after a scheduler exception without signalling them. These tests issue no model requests.
