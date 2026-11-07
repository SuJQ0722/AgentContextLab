# Browse Comp Eval

Standalone parallel Hermes runner. It does not import AIDABench; it only follows the same operational shape: JSONL input, concurrent runs, retry, resume, and per-run JSON outputs.

## Input

Put JSONL files under `data/{dataset}/`. Each row must contain:

```json
{"question": "...", "answer": "...", "type": "..."}
```

`answer` is only recorded for later evaluation. It is not sent to Hermes.

## Run

```bash
cd Browsecomp_eval
export HERMES_API_KEY="..."
export HERMES_BASE_URL="https://your-endpoint/v1"

python -m browsecomp_eval.run \
  --dataset simple_search \
  --data-path data/example/questions.jsonl \
  --model claude-opus-4-7-thinking \
  --provider custom \
  --save-name claude-opus-4-7-thinking_smoke \
  --repeats 3 \
  --num-workers 5 \
  --max-rounds 60 \
  --max-retries 3 \
  --tool-whitelist web,browser,file,terminal,code_execution \
  --skill-whitelist ""
```

Or edit environment variables and run:

```bash
scripts/run_simple_search_smoke.sh
```

## Output

For `Q` questions and `N` repeats, the runner creates `Q * N` run records:

```text
output/preds/{save_name}/{dataset}/conv/{question_id}/{question_id}__r{repeat}.json
output/preds/{save_name}/{dataset}/workspace/{question_id}__r{repeat}/attempt_{attempt}/
output/preds/{save_name}/{dataset}/summary.jsonl
```

Judge outputs are written next to the predictions:

```text
output/preds/{save_name}/{dataset}/judge/{question_id}/{question_id}__r{repeat}.json
output/preds/{save_name}/{dataset}/judge_summary.jsonl
output/preds/{save_name}/{dataset}/judge_metrics.json
```

Existing result files with `status=success` are skipped by default. `failed` and `policy_violation` runs are retried on resume. Use `--force` to rerun everything.

## Judge

After inference, run an answer-equivalence judge over `conv/**/*.json`:

```bash
export JUDGE_API_KEY="..."
export JUDGE_BASE_URL="https://your-resource.openai.azure.com"

python -m browsecomp_eval.judge \
  --pred-root output/preds/bailian_deepseek-v4-pro/browsecomp_subset_first5 \
  --judge-provider azure \
  --judge-model gpt-5-mini \
  --judge-api-version 2024-12-01-preview \
  --num-workers 5 \
  --max-retries 3
```

For OpenAI-compatible endpoints, use `--judge-provider openai --judge-base-url https://.../v1`.
Failed inference records are skipped with `score=null` and are not included in accuracy denominators unless `--include-failed` is set.

Or edit environment variables and run:

```bash
scripts/judge_browsecomp_first5.sh
```

## Whitelist

`--tool-whitelist` is a comma-separated Hermes toolset allowlist. The runner passes it to Hermes as `--toolsets`, then parses the saved session and marks a run as `policy_violation` if any actual tool call is outside the resolved allowlist.

`--skill-whitelist` is passed to Hermes as `--skills`. The default tool whitelist does not include the `skills` toolset, so the model cannot dynamically browse/load extra skills unless you explicitly allow it.

## Context selection and trajectory exports

Use `--context-engine visual|summarize|sliding_window|discard|none`.
The experimental `summarize_native` and `sliding_window_native` engines retain
unique native image payloads through text compression. Image bytes and detail
settings remain unchanged; stable hashes link retained images to source text.
These engines do not themselves enforce a matched post-compression token budget.
Budget matching must be checked by the experiment controller before scoring.
`discard_all` and `discard-all` select the full-history reset baseline: the
system instructions and original task remain, but no past assistant/tool
interactions or replacement summary survive. The evaluator sets `keep_rounds=0`.
Explicit CLI selection overrides inherited strategy variables in the child.
For older launchers, defaults are read from `CONTEXT_ENGINE`, then `CM`, then
`COMPRESS_STRATEGY`; prefer the CLI option for new experiments.

`--save-trajectories --trajectory-dir PATH` exports one JSONL record per attempt
at `PATH/iterN/question_id/attempt_A.jsonl`. Without an explicit path, enabled
exports go under the run's `trajectories/` directory. Each record includes
`messages` from available session ancestry, model, status, and run identifiers;
it is not the separate ShareGPT training export format. Attempts and parallel
workers use separate files. Historical `SAVE_TRAJECTORIES=1` and `TRAJECTORY_DIR`
settings remain accepted by this evaluator; `--no-save-trajectories` overrides
them. These variables are not global Hermes settings.
