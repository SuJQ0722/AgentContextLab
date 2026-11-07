# BC-100: two harnesses, five strategies, three repeats

Current parallel-work status: [rebuttal-status.md](rebuttal-status.md).
The core retains its 16-worker pool while supplementary work uses separate,
smaller pools and process admission reserves below 128 visible OS processes.

An audited controller-only resume path is now available:

```bash
python scripts/resume_bc_plan.py --live --resume --wait-for-lease
```

It uses the same exclusive coordinator lock and validates the frozen config,
cohort, task list, implementation hashes and harness pin before dispatching.
Structurally verified DSH post-compression budget failures remain failed terminal
observations with their original result files; they are excluded only from the
unexpected-infrastructure-failure stop counter. Budgets and strategies are not
changed, and completed/failed/timeout trials are not repeated. Explicit STOP or
a previous user pause cancels automatic standby takeover. The current standby
identity is stored in `resume-controller-service.json`; it makes no model calls
while the original coordinator holds the lease.

The campaign is defined in `configs/experiment.json:bc100_campaign`: 100 frozen
questions × 3 repeats × 5 strategies × 2 harnesses = **3,000 prediction jobs**.
The concurrency limit is **16 total**, not 16 per harness. Within each
question/repeat block, method/harness order is shuffled reproducibly. Shared
gateway and Serper caches remain warm and may be affected by concurrent jobs.

The standing instruction prohibits new Gemini calls. Consequently both new
harness runs currently select `deepseek-v4.1-flash-1017/huoshan/huoshan`;
historical Gemini + Hermes results remain separate. Changing the selected model
requires a new frozen campaign definition. This run compares harnesses on the
same model; it is not by itself a new two-model factorial experiment.

| Paper method | Hermes implementation | DSH implementation |
|---|---|---|
| No Compression | `compression.enabled=false` | `none` |
| Summarize | native `summarize` | `summarize` subclass of native DSH compaction |
| Sliding Window | native `sliding_window`, 5 recent tool results | `sliding_window_native`, native DSH retained-tail selection |
| Discard | native `discard`, keep 0 rounds | `discard` |
| VERA | native `visual` | `visual_native` |

The harnesses retain their own policy implementations. In particular, Hermes's
sliding window blanks old tool results while DSH uses its native compaction
range and a retained tail. Rendering settings are font 16 / history scale 1,
the separately calibrated legibility variant, not a byte-identical historical
VERA reproduction. Both use the 32,768 trigger and configured 131,072 context
capacity; DSH additionally checks its estimated post-compression limit 16,384.
Exact provider image-token matching across harnesses remains unvalidated. This
campaign does not replace the separately planned controlled multimodal baseline.

Each attempt retains the 60-round and 1,800-second bounds. SDK/adapter retries
inside a native call are separately distinguished from retrying an entire task.
No completed, failed, output-limited, or timed-out task is silently retried.
The initial serial pilot remains under `outputs/pilot/bc100/` and is not mixed
into this concurrent campaign. Its consumed tokens and invalid-configuration
archive remain available as separate pilot overhead.

## Start, stop, resume

```bash
# Prepare and inspect the immutable plan without inference.
python scripts/run_bc_campaign.py

# Start/resume a plan that already exists.
python scripts/run_bc_campaign.py --live --resume

# A second coordinator cannot acquire the same campaign lock.
# Stop dispatch and interrupt active workers, preserving artifacts:
touch outputs/campaigns/bc100-r3-all-strategies/STOP

# After the coordinator has exited, remove the stop marker and resume:
rm outputs/campaigns/bc100-r3-all-strategies/STOP
python scripts/run_bc_campaign.py --live --resume
```

Resume is at the **job level**, not a claim of native conversation continuation.
Every job has a fixed harness/method/question/repeat ID. Terminal results are
skipped; live workers are recognized by PID plus process-start identity;
interrupted attempts are preserved in numbered directories and explicitly
resumed as a new attempt. All attempt usage contributes to the operational
consumption report. The previous interrupted attempt is excluded from the
canonical accuracy row, never erased or treated as zero cost. Configuration
and cohort hashes must match the frozen plan. Sixteen unexpected failed jobs
halt further dispatch for diagnosis; ordinary budget limits do not halt it.

```bash
python scripts/monitor_bc_campaign.py \
  --root outputs/campaigns/bc100-r3-all-strategies --watch
python scripts/judge_bc_campaign.py \
  --root outputs/campaigns/bc100-r3-all-strategies --live --watch
```

The judge waits until all predictions terminate, then uses the frozen judge
model with at most 16 concurrent calls. It stores separate usage and does not
silently retry an interrupted or malformed judgment. No final answer within
the task budget scores zero; a failed judgment remains unscored.

## Artifacts and measurements

`outputs/campaigns/bc100-r3-all-strategies/` contains the frozen plan/config,
coordinator state, and `jobs/<harness>/<strategy>/<question>_r<repeat>/`.
Each job contains numbered `attempts/`, original harness traces, persisted
model calls and provider usage, web cache headers, render/compaction events,
and an atomic terminal result. Hermes requests/responses are gzip JSONL and
its native session database is isolated per attempt. Credentials live only in
private ignored runtime configuration; they are never added to Git.

`monitor/status.json` aggregates all attempts; `monitor/attempts.csv` retains
canonical and interrupted observations separately. Cached input, non-cache
input, output, total, usage coverage, and conservation failures are explicit.
Failed requests without usage remain unknown. Model prefix-cache hit rates and
Serper response-cache hit rates are separate. End-to-end timing includes the
trial launcher; native CLI/loop and API/SDK timings are separately labeled.
SDK timing includes internal retries and is not provider-internal latency.
No actual dollar bill is inferred from token counts without a verified tariff.

Both policy loaders are checked using local API fixtures before launching paid
work. The DSH visual transaction test uses the real PDF/Poppler renderer.
Hermes instruments its existing SDK calls and engine/render methods in the
root worker; it keeps the native `AIAgent.run_conversation` loop. DSH remains
the pinned unmodified upstream submodule; research extensions live at root.
