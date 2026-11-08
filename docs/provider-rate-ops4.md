# Ops4 dispatch reduction

`scripts/roll_sco_bc_v3_rate_ops4.py` prepares the ten cells for the explicitly recorded cloud1/local2 operational target. It creates no resources by default. It does not stop controllers or native tasks; main supervises clean drain separately. Image content, rendering, model, endpoint, task identities and existing claims remain unchanged.

Parents are independently submitted ops3 receipts under `outputs/cloud-runtime/rate-replacements`. New one-shot receipts go to `outputs/cloud-runtime/final-rate-replacements/<cell>-ops4`. Each creation copies its parent's complete argv and changes only `--job-name` and `--name`. The original image, CPU/memory specification, mount and bootstrap command are retained. Request records include the parent receipt hashes, clean-drain evidence, source hashes, configuration hash and target of one worker for that cell.

The roller waits per cell when its ops3 submission is missing or unconfirmed. An ops3 request that already selects one worker is marked `already_target_no_roll`; it is not replaced. Otherwise the old job must be `SUCCEEDED`, its bound controller must have exited zero after clean drain, and hostname/boot/PID namespace must match before retirement. A new fixed name must be explicitly absent. Existing receipt directories, including the unused legacy visual-specific receipt location, block duplicate creation even if the outcome is unknown. Failed and already claimed benchmark attempts are never released or retried.

```sh
python scripts/roll_sco_bc_v3_rate_ops4.py              # query only
python scripts/roll_sco_bc_v3_rate_ops4.py --watch --live
python -m unittest discover -s tests -p 'test_roll_sco_rate_ops4.py' -v
```

Nine mocked tests pass, covering the exact parent identity, unchanged argv, per-cell waiting, cloud1/local2 validation, already-target handling, clean-drain/absence rejection, namespace conflicts and unknown-create permanence. Testing made no cloud calls, resource mutations or model requests. The earlier visual-only draft was not launched and has been replaced by this generic implementation.

The operational target is a pressure reduction, not proof that the provider's RPM, TPM or `system_memory_limit` errors are resolved. Preserve each deployment period and its observed failures, latency and costs separately. Queue ETA still describes execution of untouched pending jobs, not recovery of every infrastructure-affected historical attempt.
