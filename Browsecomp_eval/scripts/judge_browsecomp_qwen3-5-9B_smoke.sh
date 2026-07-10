#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# Only point judge at the Qwen smoke prediction directory. Judge model/API
# configuration is inherited from the existing judge_browsecomp_first5.sh script
# or from the caller's JUDGE_* environment variables.
export DATASET="${DATASET:-browsecomp_subset_first3}"
export MODEL="${MODEL:-Qwen3-5-9B}"
export SAVE_NAME="${SAVE_NAME:-${MODEL//\//_}}"
export PRED_ROOT="${PRED_ROOT:-output/preds/${SAVE_NAME}/${DATASET}}"

exec scripts/judge_browsecomp_first5.sh
