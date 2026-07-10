#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# ── 推理结果目录 ──────────────────────────────────────────────
MODEL="${MODEL:-qwen3_5_9b_sft_sw}"
SAVE_NAME="${SAVE_NAME:-${MODEL//\//_}}"
DATASET="${DATASET:-browsecomp_subset_final}"
PRED_ROOT="${PRED_ROOT:-output/preds/${SAVE_NAME}/${DATASET}}"

# ── Judge 配置 ────────────────────────────────────────────────
JUDGE_PROVIDER="${JUDGE_PROVIDER:-openai}"
JUDGE_MODEL="${JUDGE_MODEL:-gpt-5-mini}"
JUDGE_BASE_URL="${JUDGE_BASE_URL:-https://tokenhub.sensetime.com/v1}"
JUDGE_API_VERSION="${JUDGE_API_VERSION:-2024-12-01-preview}"
JUDGE_API_KEY="${JUDGE_API_KEY:-sk-2f8nSdpTYtOEvTOraocJ3dY4jDinlHRqRgxp3974pwgbbvkp}"

JUDGE_NUM_WORKERS="${JUDGE_NUM_WORKERS:-10}"
JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-3}"
JUDGE_TIMEOUT_SECONDS="${JUDGE_TIMEOUT_SECONDS:-60}"
JUDGE_MAX_TOKENS="${JUDGE_MAX_TOKENS:-2048}"
JUDGE_TOKEN_PARAM="${JUDGE_TOKEN_PARAM:-max_completion_tokens}"
FORCE="${FORCE:-0}"
INCLUDE_FAILED="${INCLUDE_FAILED:-0}"

echo "=== Judge dsv4pro ==="
echo "  pred_root: ${PRED_ROOT}"
echo "  judge_model: ${JUDGE_MODEL}"
echo "  workers: ${JUDGE_NUM_WORKERS}"
echo ""

export JUDGE_API_KEY

args=(
  python -m browsecomp_eval.judge
  --pred-root "${PRED_ROOT}"
  --judge-provider "${JUDGE_PROVIDER}"
  --judge-model "${JUDGE_MODEL}"
  --judge-base-url "${JUDGE_BASE_URL}"
  --judge-api-version "${JUDGE_API_VERSION}"
  --num-workers "${JUDGE_NUM_WORKERS}"
  --max-retries "${JUDGE_MAX_RETRIES}"
  --timeout-seconds "${JUDGE_TIMEOUT_SECONDS}"
  --max-tokens "${JUDGE_MAX_TOKENS}"
  --token-param "${JUDGE_TOKEN_PARAM}"
)

if [[ "${FORCE}" == "1" ]]; then
  args+=(--force)
fi

if [[ "${INCLUDE_FAILED}" == "1" ]]; then
  args+=(--include-failed)
fi

"${args[@]}"