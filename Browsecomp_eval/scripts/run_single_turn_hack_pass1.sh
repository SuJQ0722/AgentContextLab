#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

TARGET_MODEL="${1:-${TARGET_MODEL:-}}"
TARGET_BASE_URL="${2:-${TARGET_BASE_URL:-}}"
TARGET_API_KEY="${3:-${TARGET_API_KEY:-}}"

if [[ -z "${TARGET_MODEL}" || -z "${TARGET_BASE_URL}" || -z "${TARGET_API_KEY}" ]]; then
  echo "Usage: bash scripts/run_single_turn_hack_pass1.sh <target_model> <target_base_url> <target_api_key>" >&2
  echo "Or set TARGET_MODEL, TARGET_BASE_URL, TARGET_API_KEY." >&2
  exit 2
fi

DATA_PATH="${DATA_PATH:-/mnt/afs_agents/sujiaqi/workspace/projects/hermes-agent/Browsecomp_eval/data/LiveBrowseComp_decrypted.jsonl.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-}"

NUM_WORKERS="${NUM_WORKERS:-20}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"
MAX_RETRIES="${MAX_RETRIES:-3}"
MAX_TOKENS="${MAX_TOKENS:-8192}"
TOKEN_PARAM="${TOKEN_PARAM:-max_tokens}"
TEMPERATURE="${TEMPERATURE:-}"
TOP_P="${TOP_P:-}"
REASONING_EFFORT="${REASONING_EFFORT:-medium}"
FORCE="${FORCE:-0}"

HERMES_API_KEY="${HERMES_API_KEY:-REDACTED_API_KEY}"
HERMES_BASE_URL="${HERMES_BASE_URL:-https://tokenhub.sensetime.com/v1}"
JUDGE_MODEL="${JUDGE_MODEL:-${MODEL:-gpt-5-mini}}"

JUDGE_NUM_WORKERS="${JUDGE_NUM_WORKERS:-20}"
JUDGE_TIMEOUT_SECONDS="${JUDGE_TIMEOUT_SECONDS:-60}"
JUDGE_MAX_RETRIES="${JUDGE_MAX_RETRIES:-3}"
JUDGE_MAX_TOKENS="${JUDGE_MAX_TOKENS:-1024}"
JUDGE_TOKEN_PARAM="${JUDGE_TOKEN_PARAM:-max_completion_tokens}"

args=(
  python browsecomp_eval/single_turn.py
  --data-path "${DATA_PATH}"
  --model "${TARGET_MODEL}"
  --base-url "${TARGET_BASE_URL}"
  --api-key "${TARGET_API_KEY}"
  --workers "${NUM_WORKERS}"
  --timeout-seconds "${TIMEOUT_SECONDS}"
  --max-retries "${MAX_RETRIES}"
  --max-tokens "${MAX_TOKENS}"
  --token-param "${TOKEN_PARAM}"
  --temperature "${TEMPERATURE}"
  --top-p "${TOP_P}"
  --reasoning-effort "${REASONING_EFFORT}"
  --judge-api-key "${HERMES_API_KEY}"
  --judge-base-url "${HERMES_BASE_URL}"
  --judge-model "${JUDGE_MODEL}"
  --judge-workers "${JUDGE_NUM_WORKERS}"
  --judge-timeout-seconds "${JUDGE_TIMEOUT_SECONDS}"
  --judge-max-retries "${JUDGE_MAX_RETRIES}"
  --judge-max-tokens "${JUDGE_MAX_TOKENS}"
  --judge-token-param "${JUDGE_TOKEN_PARAM}"
)

if [[ -n "${OUTPUT_DIR}" ]]; then
  args+=(--output-dir "${OUTPUT_DIR}")
fi

if [[ "${FORCE}" == "1" ]]; then
  args+=(--force)
fi

"${args[@]}"
