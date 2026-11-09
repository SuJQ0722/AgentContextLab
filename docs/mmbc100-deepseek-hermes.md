# MMBC-100 × 3: DeepSeek + Hermes

This is an independent campaign, `outputs/campaigns/mmbc100-hermes-deepseek-v1`.
Only Hermes runs. The exact requested route is
`deepseek-v4.1-flash-1017/huoshan/huoshan`; there is no automatic fallback.
The intended comparison is accuracy across context-management methods on MMBC.
VERA outperforming the baselines is a hypothesis, not a prerequisite for keeping
questions or results. No new DSH or Gemini predictions belong to this campaign.

## Frozen questions and images

The existing local converted MMBC source contains 400 unique questions:
`../hermes-agent/Browsecomp_eval/data/mmbrowsecomp/questions.jsonl`, SHA256
`4b39d5dfaf29111ca5b4d6577a39023f01f66bf7c67d80807b214bf08909093f`.
The converter preserves the dataset's `images` list. Of these 400 questions,
243 have initial images and 157 have none; the latter can still require visual
evidence obtained through tools.

Sort all 400 original IDs by the binary SHA256 digest of
`20261107:mmbrowsecomp:{original_id}`, then take the first 100. This extends the
existing 10-question pilot deterministically. Do not filter by image availability,
previous accuracy, method performance, or predicted difficulty. The selected 100
contain 69 with initial images (64 with one, 5 with two) and 31 without initial
images: 74 image occurrences and 74 distinct URLs. Report the initial-image and
no-initial-image groups separately as descriptive subgroups, while retaining the
same 100-question primary population for every method and repeat.

`cohort.jsonl` contains exactly `question_id`, `question`, and `image`; no answer,
checklist, canary, reference source, or hidden metadata is exposed to prediction.
The separate grader namespace stores private selected-source rows and a hash-bound
source map. Public jobs contain only these public fields and run identifiers.

Initial URLs are insufficient to freeze image content. Before final plan creation,
`mmbc_input_images.py` must store all original image bytes and the SHA-bound
`image-assets/manifest.json`. Neither a download failure nor an unsupported image
may cause replacement of a selected question. The worker verifies hashes and
copies the cached bytes without resizing. Each staged input is limited to 25 MiB;
this is an admission limit, not a claim about a provider's total request limit.

## Methods and common settings

| Method | Actual policy |
|---|---|
| `none` | No history compression |
| `discard` | Hermes discard engine, `keep_rounds=0` |
| `summarize` | Hermes summary engine, protect first 3 and last 20 messages, target ratio 0.2 |
| `sliding_window` | Hermes sliding-window engine, window size 5 |
| `visual` (VERA) | Repaired multimodal renderer, highlighted roles, text wrapping around source images/tables; keep 1 tool round, recent 5 rounds |

These five methods yield **1,500 trajectories**: 100 fixed questions × 3 repeats
× 5 methods. One CCI per method, target 16 workers per CCI. Repeats are paired
question/repeat identifiers; do not claim three independent random seeds merely
from their labels. Resume dispatches only pending, unclaimed jobs. Existing
unknown, interrupted, failed, or completed attempts are never silently retried.

Settings follow the repaired BC protocol: context window 131,072, configured
maximum output 8,192, compression trigger 32,768 using provider prompt usage
including cached input, at most 60 rounds and 1,800 seconds per trajectory.
Hermes may adjust its completion allowance internally; preserve actual request
values instead of presenting the configured value as an invariant hard limit.
VERA uses font 16, `layout=highlight`, far-history linear scale 1.0. This matches
the repaired core variant; it is not the historical default scale 0.75. Native
head/tail evidence stays native; compressed images, crops, zooms, and tables are
rendered beside their text. No DSH-specific post-compression token cap applies.

Tools are `web_search`, `web_extract`, `image_search`, `image_crop`, and
`image_zoom_in`. Serper uses the existing cached service. Fetch uses the verified
per-node text Reader on `127.0.0.1:18080`; each host must pass actual web readiness
before model dispatch. Do not inherit the root's historical remote-fetch address.

## Vanilla and additional controls

**Vanilla visual compression is pending definition and is not executable in this
plan.** No existing named vanilla policy or frozen vanilla configuration was found.
The renderer supports `plain`, `plain_no_header`, `highlight`, and
`highlight_no_wrap`, but `plain` still wraps images/tables. It is a no-highlighting
layout ablation, not automatically a complete plain-screenshot baseline. Defining
vanilla requires an explicit policy/layout intervention while preserving the
chosen evidence, trigger, retention rules, and relevant budgets. Adding it requires
a separately authorized frozen scope revision, not relabeling an existing method.

`summarize_native` and `sliding_window_native` also exist in Hermes. They remove
image blocks from the text compressor and restore unique original blocks to a
surviving user message. The existing controlled-native experiment uses a separate
matched-budget prefix protocol; it is not a completed MMBC-100 × 3 full-trajectory
arm. These two controls are not among this initial five-method plan.

Historical `text_only` rendering is not a valid synonym for vanilla: the audited
implementation drops images without automatically captioning them and may remove
table values. See [the text-only audit](experiment3/text-only-audit.md). Historic
MMBC archives contain Gemini runs, including 400-question no-compression,
discard, summary, window, visual, and text-only variants; they remain separate
from the repaired DeepSeek implementation and cannot be pooled into its repeats.

## Preparation and analysis

`prepare_mmbc100_campaign.py --prepare-inputs` freezes public inputs/config and the
private scoring map without creating an executable plan. Next stage image assets.
Once all new worker/controller sources are stable, `--prepare` checks assets and
freezes the complete plan, implementation hashes, image manifest, and jobs.
The default command only previews the cohort; it makes no API calls or writes.
`--validate` verifies the frozen campaign without requiring DSH source validation.

Use the isolated DeepSeek judge protocol and retain grading calls/usage separately
from prediction and compression calls. A generic answer-equivalence judge is not
the official checklist-based MMBC score unless that protocol is explicitly
implemented and validated. Report per-repeat accuracy and mean ± sample standard
deviation, question-cluster paired bootstrap intervals, and paired comparisons with
multiple-comparison correction when sufficiently complete. Missing scores remain
missing; report coverage and bounds before a full 100 × 3 result exists.
Failure counts are not successful completions. Nonsignificant differences do not
prove equivalence. Keep cached/non-cache/output counts and missing-field flags;
do not turn missing cache instrumentation or unavailable gateway pricing into zero.
