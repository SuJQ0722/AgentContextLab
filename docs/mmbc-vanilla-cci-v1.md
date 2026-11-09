# MMBC vanilla visual CCI v1

This is a separate 300-job campaign, `outputs/campaigns/mmbc100-hermes-vanilla-v1`, using the same 100 questions and three repeats. Every job has actual strategy `visual` and explicit `method_label: vanilla_visual`. The scientific preparer and worker define rendering without visual evidence; the deployment code does not implement or relax that ablation. The five existing methods and their frozen sources are unchanged.

The sixth CCI is `acl-mmbc100-hermes-vanilla-v1`, with eight CPUs, 32 GiB RAM and a target of 16 active trials. It retains the reviewed image, AFS mount, agents pool, VPC, zone and normal priority. There is no automatic replay of claimed jobs, unknown create responses, or terminal predictions.

```sh
# Offline preview / scientific preparation:
python scripts/provision_mmbc_vanilla_cci.py
python scripts/provision_mmbc_vanilla_cci.py --prepare
# Explicit authorized creation, once:
python scripts/provision_mmbc_vanilla_cci.py --live
python scripts/provision_mmbc_vanilla_cci.py --status
```

The launcher never publishes the independent marker at `outputs/cloud-runtime/mmbc100-hermes-vanilla-cci-v1/launch-ready.json`. After review, the operator releases that marker. The bootstrap starts Reader, validates real web readiness and invokes `run_mmbc_vanilla_campaign.py --strategy visual --concurrency 16 --resume --live`. The controller dispatches only the 300 explicitly labeled vanilla jobs via `run_mmbc_vanilla_trial.py`. A stop request drains existing children without terminating them.

```sh
# Independent operational lifecycle observer; no prediction retries:
python scripts/monitor_mmbc_vanilla_lifecycle.py --watch --live
```

This observer is excluded from the science source hashes. Receipts and status live under `outputs/cloud-runtime/mmbc100-hermes-vanilla-cci-v1/lifecycle/`. It binds the exact created UID and plan, requires matching host/boot/controller identity, confirmed bootstrap/controller exits, terminal owned attempts, explicit child-termination confirmation and no retained owned slots before issuing one official stop. Uncertain evidence leaves the resource running and reports the reason. It cannot stop any of the five original MMBC applications.

Twelve zero-model-call tests validate the vanilla-only scope, immutable claim/lease behavior, exact new entry wiring, inherited resource configuration, no repeated create, and safe lifecycle stop conditions. A real bootstrap `--dry` also verifies the independent root, label, controller and 16-worker configuration; it is not evidence of live throughput or accuracy.
