# Core BC v3 node bootstrap

`scripts/bootstrap_bc_v3_node.py` prepares one **core BC harness × method cell** on a provisioned SCO node. It does not create cloud resources or install dependencies. The SCO image, queue and AFS volume must be selected by the provisioning operator. The requested allocation is 8 CPU, 32 GiB RAM and a controller ceiling of 32 simultaneous trials. Worker child processes and threads are additional; the script reports the cgroup PID limit and measured CPU/memory capacity.

The repository and its existing campaign must be mounted at `/mnt/afs_agents/sujiaqi/workspace/projects/AgentContextLab`. Only the two core harnesses (`hermes`, `dsh`) and five core strategies (`none`, `summarize`, `sliding_window`, `discard`, `visual`) are accepted. RQ3, controlled baselines and information-loss jobs are outside this bootstrap.

The default invocation prints the commands without starting services or experiments:

```bash
python scripts/bootstrap_bc_v3_node.py --harness dsh --strategy visual
```

On the selected image, run the offline verification first:

```bash
python scripts/bootstrap_bc_v3_node.py --harness dsh --strategy visual --check
```

The actual workload command, after provisioning, is:

```bash
/opt/conda/bin/python scripts/bootstrap_bc_v3_node.py --harness dsh --strategy visual --reader-python /opt/conda/bin/python --live
```

Use the corresponding harness and strategy for each of the ten instances. `--live` is explicit; omitting it never starts a Reader or controller. The current reviewed image must supply `/opt/conda/bin/python` and the dependencies described below. A different image/interpreter requires passing its verified path and passing the same checks.

The startup sequence is:

1. Remove inherited provisioning credentials from all child environments using a basic-runtime environment allowlist. Gateway credentials continue to come from the existing research dotenv files; private image-upload credentials follow the existing Hermes helper. Cloud credential variable names in those research dotenv files are rejected. No credential values are logged.
2. Verify shared Python, Node v24.11.0, Poppler executables, selected font and package versions against `configs/cloud-runtime-v3.json`. Verify the pinned Reader source and the scientific plan's existing implementation/config/cohort hashes. No source or scientific configuration is changed.
3. Use a node-local `/tmp` `git diff` lock and disable Git optional locks/preloaded index scanning. The wrapper does not put a global lock on AFS. This reduces simultaneous index scans within one node; source validation still reads AFS and may take time.
4. Acquire one bootstrap lock per node. Reuse a healthy pinned text-only Reader on `127.0.0.1:18080`, or start it with `configs/reader-text-v1.json`. A foreign process occupying the port is not killed.
5. Execute fresh real Hermes `web_search` and `web_extract` handler checks with `preflight_bc_v3_web.py`. This writes host/boot/config-specific readiness from new observations. These are web calls, with no model inference.
6. Start the explicitly versioned heartbeat-I/O maintenance controller (`run_bc_campaign_v3_io.py`) with `--harness H --strategy S --concurrency 32 --resume --live`. Permanent shared-AFS job claims and immutable attempt paths remain the authority. Old results and unknown attempts are never imported or retried.

The shared Hermes venv currently resolves to a **node-local interpreter** at `/root/.local/share/uv/python/cpython-3.11.15-linux-x86_64-gnu/bin/python3.11`; mounting AFS alone does not supply this binary. `configs/cloud-python-stage-v3.json` identifies a SHA-verified copy of that exact standalone runtime under `outputs/cloud-runtime/`. If the interpreter is missing, `--live` safely unpacks it to its original node-local path before validation. It never changes the shared venv. Archive traversal, special files and escaping links are rejected; an existing different target is never overwritten. The stage helper copies this existing runtime, without downloading or installing packages. `--check` does not restore missing files.

The reviewed runtime includes Python 3.11.15, Pillow 12.2.0, ReportLab 5.0.0, OpenAI SDK 2.24.0, and DejaVuSans with SHA-256 `690243adfefe0ce154b547db6205794bd30ac4277275179517a90994f4980648`. A different system font selection can change pagination even with identical renderer code, so the bootstrap rejects it. Reader uses the separate system Python environment; its package versions are also recorded in the runtime reference. Do not regenerate the reference on a new node merely to bypass a mismatch.

`SIGTERM` and `SIGINT` stop new controller dispatch and wait for active trials to drain; the Reader remains available until then. A Reader failure stops further dispatch. Bootstrap logs and process IDs are under `outputs/campaigns/bc100-r3-hermes-parity-v3/runtime/nodes/{hostname}-{boot_id}/{harness}-{strategy}/`. Shared trial records hold the authoritative token/usage accounting. A cloud platform forcibly killing the entire container before draining can leave unknown attempts; permanent claims deliberately prevent automatic paid retries.

The bootstrap also owns `monitor_bc_v3_node.py --watch`, which writes node process/cgroup telemetry every 30 seconds. It stops that observer when the controller drains, without signalling model workers.

Local validation consists of four unit tests (credential filtering, exact runtime/font mismatch rejection, the one-cell 32-slot command, and archive traversal/escaping-link rejection), a dry run and an offline runtime/source check. Reference capture and offline checks make no web/model calls. Cloud resources have not been created by this script, and these checks do not prove that a future image or mount is ready.

The 34,976,734-byte staged archive was additionally restored to a disposable local directory and its interpreter returned `Python 3.11.15`. Evidence: `outputs/preflight/cloud-bootstrap-offline-20261108/result.json`. The shared venv was not modified.

The maintenance layer leaves the frozen scientific files and original plan unchanged. Each new controller and trial records `bc-v3-heartbeat-io-v1` and its implementation hashes in `maintenance.json`. Only heartbeat writes retry specified transient OS errors, up to four attempts; failures retain stage/errno evidence. Claims and terminal results retain strict writes, and old failed attempts are not retried. The initial canary used the original controller; its records retain that distinction.
