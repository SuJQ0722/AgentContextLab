#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

# --- Required: set PRED_ROOT to the prediction output directory ---
# e.g. PRED_ROOT=output/preds/finsearchcomp/gemini-3.5-flash-thinking-sw
PRED_ROOT="${PRED_ROOT:?Set PRED_ROOT to the prediction directory (e.g. output/preds/finsearchcomp/model-strategy)}"
DATA_PATH="${DATA_PATH:-data/finsearchcomp/questions.jsonl}"

JUDGE_MODEL="${JUDGE_MODEL:-gpt-5-mini}"
JUDGE_BASE_URL="${JUDGE_BASE_URL:-https://tokenhub.sensetime.com/v1}"
JUDGE_API_KEY="${JUDGE_API_KEY:-REDACTED_API_KEY}"
JUDGE_NUM_WORKERS="${JUDGE_NUM_WORKERS:-10}"
JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-3}"
JUDGE_TIMEOUT="${JUDGE_TIMEOUT:-60}"
JUDGE_MAX_TOKENS="${JUDGE_MAX_TOKENS:-2048}"
FORCE="${FORCE:-0}"
INCLUDE_FAILED="${INCLUDE_FAILED:-0}"

export JUDGE_API_KEY

args=(
  python scripts/judge_finsearchcomp.py
  --pred-root "${PRED_ROOT}"
  --data-path "${DATA_PATH}"
  --judge-model "${JUDGE_MODEL}"
  --judge-base-url "${JUDGE_BASE_URL}"
  --judge-api-key "${JUDGE_API_KEY}"
  --num-workers "${JUDGE_NUM_WORKERS}"
  --max-retries "${JUDGE_MAX_RETRIES}"
  --timeout-seconds "${JUDGE_TIMEOUT}"
  --max-tokens "${JUDGE_MAX_TOKENS}"
)

if [[ "${FORCE}" == "1" ]]; then
  args+=(--force)
fi

if [[ "${INCLUDE_FAILED}" == "1" ]]; then
  args+=(--include-failed)
fi

"${args[@]}"
