# RQ3 0.7 successor: pending predictions only

The predecessor `acl-rq3-s0700-ops2` became `SUSPENDED` at 08:10:45 UTC on 2026-11-09. The official worker listing reports its sole worker as `Deleted`; retained IP columns are historical metadata. The original controller did not write a clean-drain exit. Its 15 remaining claims all started native model calls and have no final result. They are missing outcomes with potentially unreported costs, not zero-call work.

`run_rq3_scale0700_resume_ops5.py` prepares an immutable authorization from the saved official describe and worker-list responses. It binds the original plan, experiment and cohort hashes; predecessor identity; stopped controller status; old lease; all 15 claims and occupied slots; and the new operational source hashes. Copies of predecessor evidence are archived without deleting or changing the originals.

The authorized work is exactly the **219 original unclaimed 0.7 jobs**. The other 81 observations, including all 15 paid interrupted attempts, cannot be submitted by this entry. The existing frozen scientific trial, worker, scale configuration, question, repeat, model, duration budget and score paths are reused unchanged. New claims use a separate permanent lease and 16 slots under `cloud-scale-ops5`. The old 15 slots remain intact but are not treated as live processes after verified namespace termination. Reusing their paid trajectories would require a separate, explicit recovery policy.

The successor delegates dispatch, complete atomic claim publication, native validation, no-terminal-retry handling and drain behavior to the unmodified ops2 controller. Only the authorized job selection, operational area, cutover verification and pre-publication authorization check are replaced in the new process. No existing live process or source file is patched. Another successor cannot steal this new permanent lease. Any exception or signal stops dispatch and waits for spawned deadline supervisors; it does not signal native workers or repeat a `Popen` operation.

Prepare (no model calls):

```bash
python scripts/run_rq3_scale0700_resume_ops5.py --prepare \
  --describe outputs/cloud-runtime/rq3-resume-ops5/describe.json \
  --get-workers outputs/cloud-runtime/rq3-resume-ops5/get-workers.json
```

The cloud resource runs:

```bash
/opt/conda/bin/python scripts/bootstrap_rq3_scale0700_resume_ops5.py \
  --root outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3 \
  --authorization outputs/campaigns/rq3-deepseek-bc100-r3-parity-v3/cloud-scale-ops5/scale0700-resume-authorization.json \
  --reader-python /opt/conda/bin/python --live
```

Without `--live`, the controller is dry-run only. The bootstrap supports `--dry` and `--check`. Live dispatch additionally requires exact source validation, compatible runtime, node resource checks and real host web preflight. This entry never creates cloud resources.

Validation: six new tests plus nine original controller regressions passed. Coverage includes strict SUSPENDED/Deleted proof, preserving old records, exactly 219 authorized jobs, independent 16-slot capacity despite old reservations, actual frozen trial validation and slot release, rejection of existing claims and other scales, proof mutation rejection, and natural drain after a single mock spawn. No test called a paid model API.
