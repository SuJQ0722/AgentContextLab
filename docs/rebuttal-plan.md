> **当前结果与运行状态（2026-11-14）：[全部实验、超时及rebuttal缺口](results/2026-11-14/README.md)。下文为历史规划/盘点，其中“运行中”和ETA不代表当前状态。**

# Rebuttal experiments

This branch contains experimental native-image baselines, an external DSH
adapter, and pilot launch tools. Capability probes are not scored benchmark results.

## Execution status (2026-11-07)

The subsequent parallel work is tracked in [the current rebuttal status](rebuttal-status.md):
core BC remains at 16 workers; fresh multimodal prefix capture and the independent
DeepSeek RQ3 campaign run at lower concurrency. Text-table statistics and failure
analysis are offline; the first information-loss pilot is complete. A prepared
policy or captured prefix is not a completed controlled-baseline result.

- The user stopped the serial pilot and requested a 100 × 3 run of all five
  main policies on both harnesses, with 16 total concurrent jobs. The new
  [campaign protocol and resume instructions](bc100-campaign.md) distinguish
  this 3,000-job campaign from the serial pilot and the controlled multimodal
  baseline. The frozen configuration currently obeys the standing no-new-Gemini
  instruction and selects DeepSeek for both new harness runs.
- The reviewer-facing historical cost/cache table and Pareto plots are saved
  on the `dev` worktree in [the Experiment 1 Markdown report](experiment1/experiment1.md),
  with [all 57 archived groups](experiment1/experiment1_all_runs.md) kept separately.
- The controlled native-image baseline campaign has **not** been launched.
  Implemented Hermes strategies and frozen cohorts are preparation, not results;
  matched post-compression budgets and provider image-token matching are still
  unvalidated. The BC-100 summary/visual pair is the separate DeepSeek + DSH
  transfer campaign, not completion of that controlled-baseline experiment.
- At 08:24 UTC, the corrected DSH campaign stopped after five completed attempts
  and one 1,800-second timeout (`visual_native/q_003`). The timed-out run did
  render and commit a visual compression. The monitor kept recording the stop,
  but did not autonomously recover it. The runner now treats the predeclared
  timeout as a retained budget-limited observation and advances without retrying
  that question. Grading includes deadline failures (no final answer scores 0);
  missing provider usage on interrupted streams stays unknown.
- Selected `deepseek-v4.1-flash-1017/huoshan/huoshan` from TokenHub discovery.
  Direct text, red/blue image probes, and a tool-call round trip passed. Native
  DSH headless text and image admission passed with recorded usage. Configured
  context capacity has not been stress-tested.
- Isolated Node v24.11.0 and pnpm 11.28.5 are installed. The pinned DSH build
  passed all 10 gates. The launcher invokes the built dsh CLI so task cwd is
  preserved; `pnpm --dir` would change cwd to the harness checkout.
- Audited 20,735 conversation exports; all contain harness token/cache fields,
  and 17,992 have a score. Exact session-ID joins to `summary.jsonl` recovered
  20,708 session spans. These are **not** CLI wall-clock durations: the corrected
  experiment-1 reconstruction reads `history/*.json:wall_seconds` separately.
  Legacy audit column labels have been corrected. See the reconstruction below.
- Froze 10 IDs each for BrowseComp, XBench, BrowseComp-V3, MM-BrowseComp, and
  AgenticDataBench, with seed 20261107 and dataset/content hashes. Selection is
  independent of model outcomes. Outputs: `outputs/cohorts/`.
- Hermes exposes `summarize_native` and `sliding_window_native` through its real
  loader. DSH policies live outside the pinned submodule in `plugins/dsh-context/`.
  Durable compaction tests cover summary, native window retention, and discard.
  `visual_native` renders text with the customized Hermes renderer and retains
  native attachments separately. Identify this variant explicitly; it is not a
  byte-identical rerun of historical VERA.
- DSH post-compression limits use its token meter, an estimate. Exact provider
  image-token matching is not validated. Failed compaction or an exceeded budget
  blocks the next step. Hermes native engines retain images but do not enforce
  matched post-compression budgets yet.
- BC-100 is frozen separately, in historical source order, from
  `../hermes-agent/Browsecomp_eval/data/browsecomp_subset_200/questions_100.jsonl`
  (source SHA256 `0461d4226d7bc33393abb06f6cca403234c8c6ed492626b4eb25ff513d598de7`).
  The intended paired run is 100 questions × `summarize` / `visual_native`.
- The external DSH web adapter follows Hermes `plugins/local_web`: Serper cache
  proxy and Reader server, with the configured text extraction and Jina fallback.
  Runtime secrets are read from `hermes-agent/config.yaml` (or
  `ACL_HERMES_WEB_CONFIG`) into the child environment only. Explicit DSH provider
  patches override the upstream default routing. Search cache headers and HTTP
  wall time are recorded in `web.jsonl`; missing cache headers remain null.
  Reader does not return the origin HTTP status: the DSH status field represents
  the Reader proxy status, while instrumentation marks origin status unavailable.
- The initial BC-100 launch was attempted but stopped before model inference:
  Serper `10.120.3.169:80` returned `EHOSTUNREACH`; Reader `10.120.0.246:8080`
  returned `ECONNREFUSED`. Proxy attempts returned HTTP 502. Evidence:
  initial probe logs. The user subsequently supplied replacement endpoints:
  Serper `10.120.4.249:80` works, with `X-Cached=false` then `true` for a repeat
  query (about 1.90 s then 0.006 s client-observed). Reader `10.13.64.17:8080`
  returns real page text. Preferred Reader `10.120.7.221:8080` refused both
  connection attempts, so the working alternate is selected explicitly in
  `configs/experiment.json`. Evidence: `outputs/preflight/web-new-endpoints/`.
  The 100-question paired campaign has now been launched; see
  `outputs/pilot/bc100/campaign.log` for execution status and per-run `result.json`
  for completed attempts. No benchmark score is implied by a completed turn.
  The first visual attempt exhausted its output budget before any compression.
  It remains a failed observation; the runner now continues after bounded output
  or step exhaustion without retrying it, and still stops on execution failures.
  A resumed campaign preserves all previously written attempts.
  BC-100 exposes only `web_search` / `web_fetch`, so it does not need shell
  sandbox execution. AgenticDataBench still requires a working process sandbox.
- Poppler was missing, causing the historical renderer's automatic PIL fallback.
  Earlier history-image probes are retained with `validity.json` excluding them
  from PDF-rendering claims. A local Poppler runtime is now installed; the DSH
  bridge rejects PIL fallback and partial history render failures.
- The corrected PDF synthetic probe contains 12 tool rounds and six exact recall
  fields. At font size 8 / history scale 0.75, text control returned 6/6; the image
  request consumed 8192 reasoning/output tokens with `finish_reason=length` and
  no final answer. This is an unsuccessful bounded probe, not proof that the
  route lacks image input. Native DSH also failed to finish the dense-image probe
  within its one-step bound after requesting an unavailable OCR helper tool.
  Color recognition alone is insufficient evidence of usable visual compression.
  Artifacts: `outputs/preflight/visual-history-pdf-8192/` and
  `outputs/preflight/native-visual-history-pdf/`.
- A separate legibility calibration on the same synthetic history, with font 16
  and history scale 1.0, returned 6/6 for both text and image. Provider-reported
  prompt tokens were 3732 for text and 2020 for images, for this probe only;
  they do not establish benchmark cost savings. `configs/experiment.json`
  now selects this readable DSH rendering variant, with settings preserved in
  each run manifest and render metric. Do not conflate it with historical VERA
  settings or claim independent font/scale effects from this joint change.
  Artifacts: `outputs/preflight/visual-history-pdf-8192-font16-scale1.0/`.
  The same images also passed native DSH admission and final-answer generation,
  with 6/6 exact fields and no helper tools. Its `native-dsh/result.json` records
  the completed turn, and `native-dsh/metrics/calls.jsonl` records usage.
- Native DSH successfully completed a synthetic Serper search → Reader fetch →
  final answer protocol test, using only the two web tools. This validates the
  adapter and explicit provider routing; it is not a real-backend health result.
  Artifact: `outputs/preflight/dsh-web-fixture/result.json`.

## Reproduction

```bash
bash scripts/setup.sh runtime
bash scripts/setup.sh dsh
bash scripts/setup.sh renderer  # local Ubuntu 22.04 Poppler runtime
python scripts/lab.py doctor
python scripts/probe_gateway.py  # no API calls without --live
python scripts/prepare_cohorts.py
python scripts/prepare_cohorts.py --bc100
python scripts/run_dsh_eval.py --dataset bc100 \
  --strategies summarize visual_native --limit 100 --timeout 1800
python scripts/probe_visual_history.py --font-size 16 --history-scale 1
# Add --live for paid capability probes; native DSH probe:
python scripts/probe_dsh_history.py \
  --probe-dir outputs/preflight/visual-history-pdf-8192-font16-scale1.0
python scripts/run_dsh_eval.py --dataset mmbrowsecomp \
  --strategies summarize_native sliding_window_native visual_native --limit 10
python scripts/audit_records.py --root ../hermes-agent/preds_archive \
  --output outputs/audit/archive
```

`--live` enables paid inference. BC-100 checks both real web backends before
any model request and checks the process sandbox before data tasks.
It never silently repeats an existing attempt. Completed DSH turns remain
unscored until benchmark-specific grading succeeds. `calls.jsonl` records
client-observed adapter stream time, including retries and auxiliary calls;
it is not provider-internal latency. Render and end-to-end time are separate.
Fresh sessions are supported; interrupted-session resumption and exact
cross-harness budget equivalence have not been validated.

## Continuous BC-100 supervision

On 2026-11-07 the first seven attempts were invalidated after discovering that
the loader's patch `name` is a match guard, not a plugin replacement. The old
research patch was skipped, leaving native default compaction active. Those
attempts are preserved under `outputs/invalid/bc100-policy-not-mounted-20261107T0732/`
and excluded from method comparisons. Their 2,764,249 observed tokens are reported
as invalid-configuration overhead; the interrupted request may have unreported
usage. A new cohort is necessary for valid policy comparisons, not a selective
retry based on answers. The corrected patch disables the old entry and inserts
the research subclass. Per-step and pre-request checks reject a missing/wrong
policy. Local synthetic API startup tests exercise both complete CLI boots;
the visual transaction test exercises the real PDF renderer without model calls.

`scripts/monitor_dsh.py --root outputs/pilot/bc100 --watch` checks every 30 seconds.
It verifies worker liveness, metric activity, duplicate call IDs, and token
conservation, research-policy identity, unexpected textual summarization in a
visual run, and post-compression budget validity. It records issues in `monitor/alerts.jsonl` and current state in
`monitor/status.json`. A monitor read failure is explicitly written to
`monitor/read-error.json`, never silently interpreted as zero usage. No monitor
checks make model requests, and failed experimental attempts are never replaced
with selectively successful retries. Unexpected execution failures stop the
runner for diagnosis; the monitor remains alive and reports the stopped state.
Output, step, and predeclared wall-clock limits are retained failed observations;
these advance to the next scheduled attempt without a paid retry. This policy
does not increase any per-attempt budget.

Per-call `calls.jsonl` and `monitor/calls.csv` preserve cached input, non-cache
input, cache writes, output including reasoning, totals, purpose, finish reason,
and client-observed timing. The pinned pi-ai adapter omits *zero* cache fields;
this documented convention is not applied to a missing usage object. Cache hit
rates also exclude zero-initialized usage placeholders on failed requests;
these are reported as unknown provider usage, not free calls. Cache hit
rate is the token-weighted ratio `sum(cache reads) / sum(all input)`.
Serper response-cache hits are separate from model prefix-cache hits.
Per-run `conv.json` exports Hermes-style aggregate keys and references the full
native `session.v4.jsonl.zstd` trajectory and headless event log. `records.csv`
also records observed compression counts and rendering time, with missing timing
left null. Auxiliary calls are included in overall consumption and separated by
purpose for analysis. Provider-internal latency, raw provider request IDs for
agent streams, and actual invoices are not available at this instrumentation seam.

`scripts/judge_dsh.py --live --watch` is scheduled locally to wait until all
predictions finish, then uses the existing Hermes judgment prompt with the
configured **DeepSeek** route. Empty responses score zero without an API call.
Judge requests and returned usage live in separate `judge.json` files; monitoring
reports judge consumption separately and also provides an inclusive total.
Grading does not run concurrently with predictions and is not included in agent
latency. Transport/parse failures remain unscored and are reported, not retried
silently. No new Gemini inference or judging runs are authorized or scheduled.

The current BC-100 campaign uses fixed within-question order (summary then
visual), so shared gateway cache warmth can be order-dependent. Record this
limitation rather than attributing every cache/cost difference to compression.
The invalid initial campaign may also have warmed shared cache entries for its
first four questions; no control over gateway cache eviction is assumed.
The configured seed governs cohort selection; a provider generation seed was
not set. This is a paired transfer experiment across configurations, not a
factorial isolation of model, harness, decoding, or cache-order effects.

## Experiment 1 reconstructed artifacts

Run `python scripts/rebuild_experiment1.py` (read-only inputs, no model calls),
or `--reuse` to regenerate tables/figures from its reconstruction cache.
Artifacts under `outputs/experiment1/`:

- `method_benchmark_table.csv`: 57 separate archived run groups, including
  debug/updated/ablation runs as separate rows, with token components, current
  official-price cost estimates, wall/API/render timing coverage, cache hit
  rates, compression evidence, accuracy bounds and observed score coverage.
- `per_trajectory.csv`: 22,949 archived observations including AgenticDataBench.
  All 19,238 Gemini BrowseComp-family observations have usable recorded token
  counters and can be repriced. The separate AgenticDataBench exports lack API
  token usage; tokenizer counts of saved transcripts are not substituted.
- `paired_scored_table.csv` and `paired_membership.csv`: comparisons matched on
  question-content hash and repeat, using available judged observations across
  the selected five main methods. Missing grades are not assumed incorrect.
  The full table reports coverage/bounds; paired figures condition on this
  scored intersection and are descriptive, not evidence of significance.
- `pareto_text.{png,pdf}` and `pareto_multimodal.{png,pdf}`: separate benchmark
  panels; do not pool unlike benchmarks or different models into one frontier.
- `audit.json`: provenance, coverage, and limitations. Actual CLI wall-clock was
  recovered for 22,922 observations. Complete rounded API-log timing exists for
  1,322 (1,207 Gemini); 18,752 more have only partial tail timing. Rendering
  latency is not reconstructed from unrelated timestamps. Compression counts
  have usable evidence for 7,378 records, including disabled-method zeros and
  explicitly labeled lower bounds; unreliable zero exports remain unknown.

Pricing is versioned in `configs/gemini-pricing-2026-11-07.json`, with a local
source snapshot under `outputs/audit/pricing/`. The
[Google Cloud official Standard Global table](https://cloud.google.com/model-garden/pricing)
lists Gemini 3.5 Flash at $1.50/M non-cache input, $0.15/M cached input, and
$9/M output including reasoning. The recorded gateway alias is mapped by name
for a **current-price counterfactual**, not a claim about actual historical
TokenHub bills. Tool charges and cache storage are excluded; unknown actual
costs remain null. AgenticDataBench fractional mean scores are retained separately
from exact-task accuracy. Its completed SW evaluation supersedes the partial one.

The initial matched figures place VERA below No Compression in estimated token
cost for these seven benchmarks, but accuracy tradeoffs remain (e.g., XBench
and SEAL). This supports reporting a frontier, not a universal dominance claim.
Cache-aware frozen canvases/discrete resolution levels remain an optional,
separately versioned follow-up; no unrequested Gemini rerun is needed for this
historical reconstruction.

## Priority and controls

1. **Experiment 3 first:** Summarization + Native Images and Sliding Window +
   Native Images against VERA on the three multimodal tasks. Match retained
   image tokens and post-compression total budgets. Record caption producer,
   prompt, crop description and table serialization. Implement DSH methods as
   harness plugins; preserve each native harness's execution loop.
2. **Experiment 1 in parallel using existing records:** recover provider cached
   input, non-cached input and output counts separately; report total tokens,
   per-question cost, cache hit rate and compression count. Do not substitute
   live-context estimates for billed token usage. Version the pricing source,
   billing mode, model version and date; TokenHub billed cost and hypothetical
   official Gemini prices are separate columns. Missing API/render timings are
   missing, not inferred from total latency. Only rerun missing measurements.
3. **Experiment 2:** Compare DeepSeek v4.1 Flash 1017 × DSH with the existing
   Gemini 3.5 × Hermes results. These are the two model/harness combinations
   selected for this rebuttal; no third model is planned. Match task IDs, seeds,
   tools, budgets and strategy implementation. Use two text and two multimodal
   datasets initially. Because model and harness change together, this design
   measures transfer across configurations, not either factor's isolated effect.
4. **Experiments 4–6:** paired per-question repeats and bootstrap CIs; stratified
   failure/length analysis; historical fact reconstruction and probe QA at
   multiple resolutions and distances. Predefine seeds and cohorts. Describe
   observed trends without assuming significance or lower cost in advance.

## Common run manifest

Every run should record harness tag/commit, strategy/version, exact gateway model
ID, dataset revision, question ID, repeat/seed, context and post-compression
budgets, retained image IDs/tokens, compression trigger/count, and timestamps.
Keep full provider usage and request IDs when available; never store API keys.
End-to-end time, summed API time and render time must be separately measured;
concurrent operations mean component times need not add up to elapsed time.
Token cache hit rate = cached input / total input, with zero-input cases missing.

## Existing assets

The earlier local checkout still contains the historical `preds_archive/` and
`Browsecomp_eval/output/` records. It is deliberately retained during this
migration. Configure analysis input paths explicitly; the new repository does
not upload private trajectories, datasets or environment files.

## Current boundaries

- Hermes remains the customized paper implementation, based on v0.18.0.
- DSH is pinned to `dsh-v0.2.2-rc.1`; upstream has no stable release as of
  2026-11-07. See `harness-lock.json` and `.gitmodules`.
- The shared TokenHub endpoint uses a custom OpenAI-completions provider, not
  the DSH official DeepSeek Messages provider.
- Confirm the gateway's exact Flash model ID, image support and context limits
  before treating it as a VLM experiment. Configuration is not a capability test.
