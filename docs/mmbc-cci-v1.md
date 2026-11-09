# MMBC Hermes CCI deployment v1

The frozen campaign is `outputs/campaigns/mmbc100-hermes-deepseek-v1`: 100 fixed questions × 3 repeats × five methods (`none`, `summarize`, `sliding_window`, `discard`, `visual`), for 1,500 jobs. Vanilla visual is not authorized by this implementation. Each method has one independent CCI, eight CPUs, 32 GiB RAM, and a target of 16 active trials. Five allocations request 40 CPUs and 160 GiB altogether. A configured trial target is not evidence of simultaneous API requests or successful predictions.

The reviewed CCI7 image, AFS mount, agents pool, VPC, zone and normal priority are retained. The launcher uses explicit `bash -c` argv and a separate launch marker. Credentials are not embedded in the CCI configuration. The scientific plan records the controller, bootstrap and launcher hashes; those files must remain unchanged after preparation.

```sh
# Offline preview; no cloud/model calls.
python scripts/provision_mmbc_cci_v1.py
# After the campaign plan and assets are frozen:
python scripts/provision_mmbc_cci_v1.py --prepare
# Explicit authorized create, once per fixed application name:
python scripts/provision_mmbc_cci_v1.py --live
# Read-only platform status:
python scripts/provision_mmbc_cci_v1.py --status
```

Creation does not publish `outputs/cloud-runtime/mmbc100-hermes-cci-v1/launch-ready.json`. The operator publishes that marker only after reviewing the prepared campaign. The bootstrap validates the plan, starts the same text Reader service, checks actual search/fetch readiness and starts `run_mmbc100_campaign.py` for the requested method. It records node identity, controller PID, service failures and exit status.

The controller publishes complete claim and slot owners before starting a supervisor, uses the shared per-cell 16-slot limit, and dispatches only unclaimed jobs. Unknown attempts and create outcomes are never automatically repeated. A campaign `STOP`, method-specific `stops/<strategy>`, or SIGTERM stops new dispatch and lets existing trials drain. Persistent leases are not silently reclaimed.

## Completion and automatic resource cleanup

```sh
# Read-only once; does not stop an application.
python scripts/monitor_mmbc_cci_lifecycle.py
# Authorized persistent cleanup observer:
python scripts/monitor_mmbc_cci_lifecycle.py --watch --live
```

The lifecycle observer is an independent operational component, excluded from scientific source hashes. Its receipts, service identity and status history live under `outputs/cloud-runtime/mmbc100-hermes-cci-v1/lifecycle/`. Each application also gets an immutable UID binding and, at most once, a stop request/response.

Automatic stop requires the exact submitted application UID and plan, matching bootstrap/controller host, boot and process namespace, a bootstrap exit, a drained controller exit, terminal results for every owned claim, explicit child-termination confirmation and no retained owned slot. A proven bootstrap failure before any controller or native claim can also be cleaned up. Missing or contradictory evidence leaves the instance running and reports `unknown_no_stop`. The observer neither publishes the launch marker nor retries predictions. CCI containers sleep after bootstrap exit to prevent platform restarts from replaying the experiment; the observer stops those completed allocations.

Validation: six orchestration tests cover complete claims, durable leases, stop-before-dispatch, exact resource/argv wiring and unknown-create nonreplay. Five lifecycle tests cover identity binding, required drain evidence, retained slots, absent markers and single stop issuance. These tests make no paid model calls.
