# AgentContextLab

**Understanding Context Management for Long-Horizon Agents**

Research code for [When History Is Multimodal: Rethinking Context Management for Long-Horizon Agents](https://arxiv.org/abs/2608.29897).

How should agents retain, compress, and represent their interaction history? AgentContextLab studies this question through controlled comparisons of context-management strategies, examining task accuracy, token cost, history retention, and evidence preservation across text and multimodal tasks.

The project combines a common evaluation harness, context-engine baselines, and analysis tools. It also includes VERA, our training-free visual context manager, which preserves native visual evidence alongside rendered historical text.

## Research focus

- Compare No Compression, Discard-All, Sliding Window, Summarization, and Visual Rendering under shared experimental conditions.
- Analyze how retaining older history and changing visual fidelity affect accuracy and inference cost.
- Study when native images and structured artifacts provide evidence that text-only representations lose.

See the [table wrapping gallery](docs/table-wrap-cases/README.md) for generated rendering examples and reproduction instructions.

This repository extends [Hermes Agent](https://github.com/NousResearch/hermes-agent) with context-engine plugins, visual tools, and an evaluation harness. The original Hermes documentation is preserved in [Hermes README](hermes-agent/README.md).

## Context strategies

| Strategy | Configuration | Behavior |
|---|---|---|
| Visual rendering / VERA | `context.engine: visual` | Render historical text with native visual evidence; configure history resolution and recent context retention. |
| Summarization | `context.engine: summarize` | Replace managed history with a structured text summary. |
| Sliding window | `context.engine: sliding_window` | Replace older tool outputs with placeholders. |
| Discard-All | `context.engine: discard`, `keep_rounds: 0` | Remove historical interactions, preserving only system instructions and the original task. |
| No compression | `compression.enabled: false` | Keep history without context compression. |

`discard_all` and `discard-all` are accepted legacy names for the discard engine. The optional `keep_rounds` setting supports partial retention; use zero for the Discard-All baseline.

## Repository layout

```text
AgentContextLab/
├── .env.example              # clean shared TokenHub template
├── .env                      # local shared URL/key, ignored
├── configs/                  # model settings and DSH provider overlay
├── scripts/                  # setup, launchers, evaluation entrypoints
├── docs/                     # rebuttal plan and rendered table cases
├── harness-lock.json          # exact harness revisions and release status
├── hermes-agent/              # customized Hermes source and its own .env
└── deepseekHarness/           # official DSH submodule and its own .env
```

The `dev` branch is the multi-harness research workspace. The original flat
paper-code layout remains on `main`. Local development now lives in an
`AgentContextLab` directory; the earlier `hermes-agent` checkout and its logs are
retained as a migration backup.

## Setup

```bash
git clone --recurse-submodules https://github.com/SuJQ0722/AgentContextLab.git
cd AgentContextLab
git switch dev
git submodule update --init deepseekHarness
cp .env.example .env
cp configs/deepseekHarness.env.example deepseekHarness/.env
# Fill in TOKENHUB_BASE_URL and TOKENHUB_API_KEY locally.
# Verify model ID and capabilities in configs/experiment.json.
bash scripts/setup.sh hermes python3.11
bash scripts/setup.sh renderer  # local Poppler, Ubuntu 22.04
source .venv/bin/activate
# DSH requires Node >=24.9 and the pnpm version in its package.json.
bash scripts/setup.sh dsh
python scripts/lab.py doctor
```

DSH is locked to `dsh-v0.2.2-rc.1`. Upstream has no stable release as of
2026-11-07; this is a reproducible release candidate, not a stability claim.
Hermes preserves the paper's customized v0.18.0-based code. Its ordinary setup
instructions remain in [hermes-agent/README.md](hermes-agent/README.md).

Root `.env` holds shared TokenHub settings. Optional harness-specific overrides
stay in `hermes-agent/.env` and `deepseekHarness/.env`. Shared gateway values take
precedence in the launchers; credentials are passed through the environment and
never embedded in the generated provider config or printed dry-run commands.
The DSH local-env template is [configs/deepseekHarness.env.example](configs/deepseekHarness.env.example).

## Run and inspect

```bash
python scripts/lab.py run hermes --prompt 'Your task' --dry-run
python scripts/lab.py run dsh --prompt 'Your task' --dry-run
# Remove --dry-run only when ready to call the configured model.
python scripts/eval_hermes.py -- --help
python scripts/render_table_wrap_cases.py
```

The DSH overlay selects a custom OpenAI Chat Completions route for TokenHub's
`/v1` gateway. DSH's official DeepSeek adapter uses a different Messages protocol.
Exact model ID, image support and token limits must be verified at your endpoint.

See [the rebuttal plan](docs/rebuttal-plan.md) for experimental order and controls,
and [Hermes evaluation documentation](hermes-agent/Browsecomp_eval/README.md) for
existing benchmark runs and trajectory exports. Experimental DSH context plugins
and Hermes Native Images baselines are implemented; validation status and remaining
execution blockers are recorded in the rebuttal plan. No scored pilot results have
been produced yet. Setup, doctor and dry-run do not start paid runs.

## Checks

```bash
python -m unittest discover -s tests -v
cd hermes-agent
scripts/run_tests.sh tests/agent/test_eval_context_compat.py tests/agent/test_visual_table_render.py
```

## Citation

```bibtex
@article{su2026history,
  title={When History Is Multimodal: Rethinking Context Management for Long-Horizon Agents},
  author={Su, Jiaqi and Pang, Cong and Hong, Jiawei and Yao, Tiankuo and Chen, Zixuan and Lou, Xin and Lu, Lewei},
  journal={arXiv preprint arXiv:2608.29897},
  year={2026}
}
```

## Acknowledgments and license

Built on Hermes Agent by Nous Research and its contributors. Original attribution is retained. See [LICENSE](LICENSE) for the MIT license; third-party datasets and services retain their respective terms.
