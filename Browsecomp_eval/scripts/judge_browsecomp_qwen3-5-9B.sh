#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Judge the full 100-question Qwen prediction directory. Judge API settings
# are inherited from judge_browsecomp_first5.sh or caller-provided JUDGE_* envs.
export DATASET="${DATASET:-browsecomp_subset_200}"
export MODEL="${MODEL:-Qwen3-5-9B}"
export SAVE_NAME="${SAVE_NAME:-${MODEL//\//_}}"
export PRED_ROOT="${PRED_ROOT:-output/preds/${SAVE_NAME}/${DATASET}}"

exec scripts/judge_browsecomp_first5.sh
