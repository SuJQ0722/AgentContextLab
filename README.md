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

This repository extends [Hermes Agent](https://github.com/NousResearch/hermes-agent) with context-engine plugins, visual tools, and an evaluation harness. The original Hermes documentation is preserved in [README.hermes.md](README.hermes.md).

## Context strategies

| Strategy | Configuration | Behavior |
|---|---|---|
| Visual rendering / VERA | `context.engine: visual` | Render historical text with native visual evidence; configure history resolution and recent context retention. |
| Summarization | `context.engine: summarize` | Replace managed history with a structured text summary. |
| Sliding window | `context.engine: sliding_window` | Replace older tool outputs with placeholders. |
| Discard-All | `context.engine: discard`, `keep_rounds: 0` | Remove historical interactions, preserving only system instructions and the original task. |
| No compression | `compression.enabled: false` | Keep history without context compression. |

`discard_all` and `discard-all` are accepted legacy names for the discard engine. The optional `keep_rounds` setting supports partial retention; use zero for the Discard-All baseline.

## Setup

Use Python 3.11–3.13 and install this checkout:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -e ./Browsecomp_eval
pip install reportlab pymupdf Pillow
hermes setup
```

Configure a vision-capable model for visual context and the tool backends required by your experiment. Provider credentials and datasets must be supplied separately. The optional `local_web` integration requires its own search/fetch services; it is not a public hosted service bundled with this repository.

Example configuration in the selected Hermes profile:

```yaml
context:
  engine: visual
  strategy_config:
    history_scale: 0.75
    layout: highlight
```

For the reset baseline:

```yaml
context:
  engine: discard
  strategy_config:
    keep_rounds: 0
```

## Evaluation

The bundled runner accepts JSONL datasets and creates isolated per-question runs:

```bash
cd Browsecomp_eval
python -m browsecomp_eval.run \
  --dataset example \
  --data-path data/example/questions.jsonl \
  --model YOUR_VISION_MODEL \
  --provider YOUR_PROVIDER \
  --context-engine visual \
  --save-name visual-example \
  --save-trajectories \
  --trajectory-dir output/trajectories/visual-example
```

See [Browsecomp_eval/README.md](Browsecomp_eval/README.md) for input/output details. Paper-wide reproduction also requires the corresponding benchmark data and external task environments; the AgenticDataBench environment is maintained separately.

Trajectory exports contain session history in `messages` format, including available pre-compression ancestors. Each question, repeat, and retry attempt has its own JSONL file. These are evaluation exports, not Hermes's separate ShareGPT training export format.

## Code map

- `plugins/context_engine/visual/`: visual memory construction and PDF/image rendering.
- `plugins/context_engine/{discard,sliding_window,summarize}/`: comparison strategies.
- `tools/image_{search,crop,zoom_in}_tool.py`: visual evidence acquisition and inspection.
- `Browsecomp_eval/`: parallel evaluation, session traces, judging, and analysis.

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
