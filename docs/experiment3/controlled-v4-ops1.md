# Controlled v4 operational concurrency update

The operational coordinator `scripts/run_controlled_native_v4_ops1.py` keeps the pilot target at4, then changes the requested target to16 **only after all six pilot results satisfy the existing budget/native gate**. The actual number admitted can be lower: it uses the unchanged shared `experiment_admission_v4.py` lock and reservation ledger, reserves two local core tasks, and requires fewer than128 visible local processes. RQ3 and existing core workers remain included in capacity accounting.

The frozen v4 plan, scientific worker, prefix data, configuration, budget conditions, model route, tools, trial timeout and results are unchanged. The archived plan still records its original concurrency4; `operational-coordinator-ops1.json` explicitly records the operational override, source hashes and start time. Changes in concurrency can affect latency/cache behavior and must be attributed to this deployment phase, not presented as identical operating conditions.

For an already stopped coordinator, resume with:

```sh
python scripts/run_controlled_native_v4_ops1.py --live
```

For an actively running original v4 coordinator, the explicit one-time handoff also requires `--handoff --expected-pid PID --expected-identity START_ID`. It verifies the original script, root, PID/start identity and stored coordinator record. While holding the same admission flock, it waits for a fresh old-coordinator status checkpoint written after that coordinator's spawn/dispatch loop and verifies matching durable dispatch records for live trial supervisors. This closes the window between spawning a paid child and publishing its dispatch, including a child that terminates quickly. Failure to establish that checkpoint aborts without signaling the coordinator.

Only the verified coordinator is signaled through a Linux pidfd. Where this Conda Python omits the standard wrappers, the verified Linux x86_64 syscall interface is used; it never falls back to an identity-racy PID kill. A self-PID signal0 test verifies that interface without terminating a process. No process group, supervisor or model worker is terminated. After confirmed coordinator exit, the replacement obtains the original queue lock and adopts existing dispatch/supervisor records. Unknown or terminal paid attempts are not automatically retried. Newly admitted trials still invoke the exact frozen v4 trial entrypoint. `ops1-handoff.json` records the preserved supervisor identities and the publication checkpoint; the new coordinator adds its separate operational lineage.

Five focused tests cover strict gate-to-target selection, missing/mismatched dispatch publication, the fresh checkpoint required even for a short-lived child, and rejection of a wrong identity or trial PID. The default invocation performs validation and prints the requested targets without starting or signaling anything.
