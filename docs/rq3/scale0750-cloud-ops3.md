# RQ3 0.75 cloud execution scope

The final requested scales are 0, 0.25, 0.5, 0.7, 0.75, 0.8 and 1. The 0.125 runs remain archived and excluded from this comparison. This new operational entry executes only the 300 authorized 0.75 jobs (100 questions × three repeats); the other 1,800 jobs in its compatibility plan are placeholders and cannot be dispatched.

The independent campaign is `outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1`. Its frozen scientific scope is implemented by `prepare_rq3_scale0750_v1.py`, `run_rq3_scale0750_trial.py` and `rq3_scale0750_worker.py`. The new controller checks the exact scope, source hashes and separate cloud launch authorization. It neither edits nor replays the six existing scale cohorts.

```bash
python scripts/bootstrap_rq3_scale0750_ops3.py \
  --root outputs/campaigns/rq3-deepseek-bc100-r3-scale0750-v1 \
  --scale 0.75 --reader-python /opt/conda/bin/python --live
```

The bootstrap requires the existing 8 CPU / 32 GiB runtime reference, font, Poppler, Node and Python dependencies. It starts the loopback Reader, performs a real host-specific web preflight, and then starts `run_rq3_scale0750_cloud_ops3.py` with 16 slots and `--resume --live`. Credentials for cloud administration are excluded from model-worker environment inheritance. Reader, controller and node resource telemetry are recorded separately.

Dispatch uses permanent claims and an exclusive scale lease. Existing attempts and ambiguous partial claims are never replayed automatically. Root STOP, `cloud-scale-ops3/STOP`, `cloud-scale-ops3/stops/scale_0750`, signals and unexpected controller errors stop new dispatch; existing native children drain under their original supervisors. Reader failure also stops dispatch and keeps the Reader alive until draining finishes. No operational failure triggers a new model request automatically.

Validation completed on 2026-11-09 with zero model calls:

- Twelve tests passed, covering strict scale and authorized-ID gates, scientific-parameter preservation, exact launch binding, atomic claims, 16 slots, duplicate prevention, exception/signal draining, credential isolation and Reader shutdown order.
- The actual controller dry run selected exactly 300 jobs. Actual `verify_scope` and `verify_launch` passed.
- Actual bootstrap `--check` passed; the runtime record is `outputs/preflight/rq3-scale0750-bootstrap-ops3-check.json`. This offline check is distinct from the real web preflight that each cloud node must execute before live dispatch.
- The original active ops2 controller and bootstrap hashes remained unchanged.

Frozen bindings:

| Artifact | SHA-256 |
|---|---|
| Scientific plan | `992350b26155acbc4350dae606ce09d3015c6545bf16150d2273de50851ec37e` |
| Scientific scope | `5e7f716861141eeef9be11cacd7caff42dc4e114cd57907ed1c4a56b28b6c25e` |
| Cloud launch authorization | `03bce05e89bc93c9a1439907b4b398b4a22f6dcb19a4ea5e4b5204eed72a21a4` |
| New controller | `a14af778ace8116dbd83050af8aea8da17a9d9d38dcea5525cf5625fc57444fc` |
| New bootstrap | `7a12f84e362e08c405b40d864db90f9a85d1c4b21677e913edebbb918fe46f36` |

These checks establish execution readiness; they do not establish completed scientific results or successful cloud deployment.
