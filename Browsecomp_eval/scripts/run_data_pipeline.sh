#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(cd .. && pwd)"
export PYTHONPATH="${PROJECT_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
export HERMES_BUNDLED_PLUGINS="${PROJECT_ROOT}/plugins"

if [[ -z "${HERMES_HOME:-}" && -f "${HOME}/.hermes/active_profile" ]]; then
  ACTIVE_PROFILE="$(tr -d '[:space:]' < "${HOME}/.hermes/active_profile")"
  if [[ -n "${ACTIVE_PROFILE}" && "${ACTIVE_PROFILE}" != "default" ]]; then
    export HERMES_HOME="${HOME}/.hermes/profiles/${ACTIVE_PROFILE}"
  fi
fi

HERMES_CONFIG_SOURCE="${HERMES_CONFIG_SOURCE:-${PROJECT_ROOT}/config.yaml}"
HERMES_CONFIG_TARGET="${HERMES_CONFIG_TARGET:-${HERMES_HOME:-${HOME}/.hermes}/config.yaml}"
if [[ "${SYNC_HERMES_CONFIG:-1}" == "1" && -f "${HERMES_CONFIG_SOURCE}" ]]; then
  mkdir -p "$(dirname "${HERMES_CONFIG_TARGET}")"
  cp "${HERMES_CONFIG_SOURCE}" "${HERMES_CONFIG_TARGET}"
  echo "Synced Hermes config: ${HERMES_CONFIG_SOURCE} -> ${HERMES_CONFIG_TARGET}"
fi

# ── Configuration ────────────────────────────────────────────
HERMES_API_KEY="${HERMES_API_KEY:-sk-2f8nSdpTYtOEvTOraocJ3dY4jDinlHRqRgxp3974pwgbbvkp}"
HERMES_BASE_URL="${HERMES_BASE_URL:-https://tokenhub.sensetime.com/v1}"
MODEL="${MODEL:-gpt-5.5}"
PROVIDER="${PROVIDER:-custom}"
HERMES_BIN="${HERMES_BIN:-/root/.local/bin/hermes}"

# Data
DATA_SOURCE="${DATA_SOURCE:-/mnt/afs_agents/sujiaqi/workspace/projects/hermes-agent/Browsecomp_eval/data/random10.jsonl}"
DATASET="${DATASET:-data_pipeline}"
FIRST_N="${FIRST_N:-10}"
DATA_PATH="${DATA_PATH:-data/${DATASET}/questions.jsonl}"
EXPECTED_TOTAL="${EXPECTED_TOTAL:-10}"

# Run params
SAVE_NAME="${SAVE_NAME:-${MODEL//\//_}}"
REPEATS="${REPEATS:-1}"
NUM_WORKERS="${NUM_WORKERS:-5}"
MAX_ROUNDS="${MAX_ROUNDS:-200}"
MAX_RETRIES="${MAX_RETRIES:-3}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-3600}"
CONTEXT_LENGTH="${CONTEXT_LENGTH:-262144}"
COMPRESS_THRESHOLD="${COMPRESS_THRESHOLD:-65536}"
CM="${CM:-compressor}"
HERMES_QUIET="${HERMES_QUIET:-1}"
FORCE="${FORCE:-0}"

# Session storage: <base>/<dataset>/<model>/iter_N/<q_id>/main|subagents/
HERMES_SESSION_STORAGE_ROOT="${HERMES_SESSION_STORAGE_ROOT:-${PROJECT_ROOT}/Browsecomp_eval/output/data_synthesis}"

# Toolsets
TOOL_WHITELIST="${TOOL_WHITELIST:-web,browser,code_execution}"
SKILL_WHITELIST="${SKILL_WHITELIST:-}"

if [[ ! -x "${HERMES_BIN}" ]]; then
  echo "Hermes executable not found or not executable: ${HERMES_BIN}" >&2
  exit 2
fi

# ── Validate & prepare dataset ───────────────────────────────
python - "${DATA_SOURCE}" "${DATA_PATH}" "${EXPECTED_TOTAL}" "${FIRST_N}" <<'PY'
import json, sys
from pathlib import Path

source = Path(sys.argv[1])
output = Path(sys.argv[2])
expected_total = int(sys.argv[3])
first_n = int(sys.argv[4])

if not source.is_file():
    raise SystemExit(f"data source not found: {source}")

rows = []
total = 0
with source.open("r", encoding="utf-8") as f:
    for line in f:
        if not line.strip():
            continue
        total += 1
        row = json.loads(line)
        if len(rows) < first_n:
            rows.append(row)

if total < expected_total:
    raise SystemExit(f"expected >= {expected_total} rows, found {total}: {source}")

output.parent.mkdir(parents=True, exist_ok=True)
with output.open("w", encoding="utf-8") as f:
    for row in rows:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

print(f"Dataset: {total} total rows, wrote first {len(rows)} to {output}")
PY

if [[ "${PREPARE_ONLY:-0}" == "1" ]]; then
  exit 0
fi

# ── Exports ──────────────────────────────────────────────────
export NO_PROXY="10.120.4.40,localhost,127.0.0.1,::1"
export no_proxy="${NO_PROXY}"
export HERMES_API_KEY
export HERMES_BASE_URL
export HERMES_SESSION_STORAGE_ROOT
export COMPRESS_THRESHOLD
export CM

# ── Run ──────────────────────────────────────────────────────
args=(
  python -m browsecomp_eval.run
  --dataset "${DATASET}"
  --data-path "${DATA_PATH}"
  --model "${MODEL}"
  --provider "${PROVIDER}"
  --base-url "${HERMES_BASE_URL}"
  --hermes-bin "${HERMES_BIN}"
  --save-name "${SAVE_NAME}"
  --repeats "${REPEATS}"
  --num-workers "${NUM_WORKERS}"
  --max-rounds "${MAX_ROUNDS}"
  --max-retries "${MAX_RETRIES}"
  --timeout-seconds "${TIMEOUT_SECONDS}"
  --context-length "${CONTEXT_LENGTH}"
  --compression-threshold "${COMPRESS_THRESHOLD}"
  --context-engine "${CM}"
  --prompt-mode data_synthesis
  --tool-whitelist "${TOOL_WHITELIST}"
  --skill-whitelist "${SKILL_WHITELIST}"
  --ignore-rules
)

if [[ "${HERMES_QUIET}" == "0" ]]; then
  args+=(--no-quiet)
fi
if [[ "${FORCE}" == "1" ]]; then
  args+=(--force)
fi

echo ""
echo "=== Data Pipeline Run ==="
echo "  model: ${MODEL}"
echo "  dataset: ${DATASET}"
echo "  questions: ${FIRST_N}"
echo "  repeats: ${REPEATS}"
echo "  workers: ${NUM_WORKERS}"
echo "  session_root: ${HERMES_SESSION_STORAGE_ROOT}"
echo "  session_path: <root>/${DATASET}/${SAVE_NAME}/iter_N/<q_id>/main/"
echo ""

"${args[@]}"
