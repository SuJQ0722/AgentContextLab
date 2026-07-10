#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

: "${HERMES_API_KEY:?Set HERMES_API_KEY before running this script}"

DATASET="${DATASET:-simple_search}"
DATA_PATH="${DATA_PATH:-data/example/questions.jsonl}"
MODEL="${MODEL:-claude-opus-4-7-thinking}"
PROVIDER="${PROVIDER:-custom}"
BASE_URL="${BASE_URL:-${HERMES_BASE_URL:-}}"
SAVE_NAME="${SAVE_NAME:-${MODEL}_smoke}"
REPEATS="${REPEATS:-1}"
NUM_WORKERS="${NUM_WORKERS:-5}"
MAX_ROUNDS="${MAX_ROUNDS:-60}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TOOL_WHITELIST="${TOOL_WHITELIST:-web,browser,file,terminal,code_execution}"
SKILL_WHITELIST="${SKILL_WHITELIST:-}"

echo "开始时间: $(date)"
echo "模型: ${MODEL}  (save_name=${SAVE_NAME})"
echo "dataset: ${DATASET}"
echo "data_path: ${DATA_PATH}"
echo "并行: ${NUM_WORKERS}  repeats: ${REPEATS}  retry: ${MAX_RETRIES}  rounds: ${MAX_ROUNDS}"
echo "tool whitelist: ${TOOL_WHITELIST}"
echo "skill whitelist: ${SKILL_WHITELIST:-none}"
echo ""

python -m browsecomp_eval.run \
  --dataset "${DATASET}" \
  --data-path "${DATA_PATH}" \
  --model "${MODEL}" \
  --provider "${PROVIDER}" \
  --base-url "${BASE_URL}" \
  --save-name "${SAVE_NAME}" \
  --repeats "${REPEATS}" \
  --num-workers "${NUM_WORKERS}" \
  --max-rounds "${MAX_ROUNDS}" \
  --max-retries "${MAX_RETRIES}" \
  --tool-whitelist "${TOOL_WHITELIST}" \
  --skill-whitelist "${SKILL_WHITELIST}"

echo ""
echo "全部完成: $(date)"
